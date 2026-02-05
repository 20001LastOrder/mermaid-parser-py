from loguru import logger
from mermaid_parser.structs.state_diagram import (
    StateDiagramWithNote,
    HistoryState,
)
from mermaid.statediagram.state import Composite, Concurrent, End, Start, State
from mermaid.statediagram.transition import Choice, Fork, Join, Transition
from mermaid_parser import MermaidParser
import networkx as nx
import re

"""
Currently, this class gives basic support for converting flat state diagrams.
Supports:
- Basic states and transitions
- Composite (hierarchical) states
- Parallel regions (via -- separator)
- History states (shallow)

# TODO: Add support for Fork and Join transitions
# TODO: Add support for Choice transitions
# TODO: Add support for converting to networkx graph
"""


class StateDiagramConverter:
    def __init__(self):
        self.parser = MermaidParser()
        self.history_states = {}  # Maps composite state ID -> HistoryState object
        self.history_transitions = (
            {}
        )  # Maps (from_state, trigger) -> target_composite_state for history

    def convert(self, mermaid_text: str) -> StateDiagramWithNote:
        # Reset history state tracking for each conversion
        self.history_states = {}
        self.history_transitions = {}

        # TODO: the current parser does not handle rendering styles
        parsed_data = self.parser.parse(mermaid_text)
        graph_type = parsed_data.get("graph_type")
        if "stateDiagram" not in graph_type:
            raise ValueError(f"Unsupported graph type: {graph_type}")

        all_states = {}
        states, transitions = self._convert_state_diagram(
            parsed_data["graph_data"]["rootDoc"], all_states
        )

        # Add history states to the states list
        for history_state in self.history_states.values():
            states.append(history_state)

        # Extract initial states from transitions
        root_initial_state, initial_states = self._extract_initial_states(transitions)

        result = StateDiagramWithNote(
            title="State Diagram",
            states=states,
            transitions=transitions,
            version="v2",
            root_initial_state=root_initial_state,
            initial_states=initial_states,
        )

        # Attach history state info to the result for consumers
        result.history_states = self.history_states
        result.history_transitions = self.history_transitions

        return result

    def _extract_initial_states(self, transitions: list) -> tuple:
        """
        Extract initial states from transitions.

        A root-level initial state is one where [*] transitions to a state with no parent.
        Nested initial states are where [*] transitions to a state with a parent.

        Returns:
            tuple: (root_initial_state, initial_states_dict)
                - root_initial_state: The ID of the root-level initial state (or None)
                - initial_states_dict: Map of parent_id -> initial child state ID
        """
        root_initial_state = None
        initial_states = {}  # parent_id -> initial_state_id

        for transition in transitions:
            from_state = getattr(transition, "from_state", None)
            to_state = getattr(transition, "to_state", None)

            if not from_state or not to_state:
                continue

            from_id = getattr(from_state, "id_", None)
            to_id = getattr(to_state, "id_", None)

            # Check if this is an initial state transition ([*] or _start)
            if from_id in ["root_start", "[*]"] or (from_id and "_start" in from_id):
                to_parent = getattr(to_state, "parent_id", None)

                if to_parent is None:
                    # This is the root-level initial state
                    if root_initial_state is None:
                        root_initial_state = to_id
                        logger.debug(f"Found root initial state: {to_id}")
                else:
                    # This is a nested initial state
                    if to_parent not in initial_states:
                        initial_states[to_parent] = to_id
                        logger.debug(f"Found initial state for {to_parent}: {to_id}")

        return root_initial_state, initial_states

    def _convert_states_and_notes(
        self,
        root_doc: list[dict],
        all_states: dict[str, State],
        parent_id: str = None,
        parent_path: str = None,
    ) -> tuple[dict[str, State], list[Transition]]:
        """
        Extract and convert states and transitions from parsed state diagram data.

        Three-pass approach to correctly handle state hierarchy:
        1. First pass: Process state declarations (but not their nested content yet)
        2. Second pass: Process transitions at this level (now all states at this level are known)
        3. Third pass: Recursively process nested content of composite states

        Args:
            root_doc: List of parsed state diagram elements
            all_states: Dictionary to store all states by id
            parent_id: ID of the parent state (for nested states) - this is the simple parent, e.g. 'Print'
            parent_path: Full hierarchical path to parent, e.g. 'On_LoggedIn_Print' - used for scoped keys

        Returns:
            Tuple of (states_dict, transitions_list)
        """
        # If parent_path is not provided, use parent_id
        if parent_path is None:
            parent_path = parent_id
        states = {}  # Dict to store states by id
        transitions = []  # List to store transitions
        composite_states = []  # Track composite states for third pass
        divider_regions = []  # Track divider regions for parallel state handling

        # PASS 1: Process state declarations and notes (but don't recurse into composite states yet)
        for item in root_doc:
            # Skip items that are strings (simple state declarations like "state ProgramComplete")
            # These will be handled when they appear in transitions
            if isinstance(item, str):
                continue

            if item["stmt"] == "state":
                state_id = item["id"]

                # Check if this is a divider (parallel region marker)
                if item.get("type") == "divider":
                    # Track divider regions for later processing
                    divider_regions.append(item)
                    continue

                scoped_key = self._get_scoped_key(state_id, parent_path)

                # Handle regular state items and composite states
                if scoped_key not in all_states:
                    state = self._create_state(item, parent_id, scoped_id=scoped_key)
                    if state:
                        states[state_id] = state
                        all_states[scoped_key] = state

                        # If this is a composite state, save it for later processing
                        if "doc" in item:
                            composite_states.append((state_id, item["doc"]))
                else:
                    # State already exists - just update description if provided
                    description = item.get("description", "")
                    if description and state_id in states:
                        states[state_id].content = description

        # PASS 2: Recursively process nested content FIRST if we're at root level
        # This ensures deeply nested states exist before root tries to reference them
        # For non-root levels, process transitions first (breadth-first within nested scopes)
        if parent_id is None:
            # Root level: process nested scopes first
            for comp_state_id, comp_doc in composite_states:
                new_parent_path = (
                    f"{parent_path}_{comp_state_id}" if parent_path else comp_state_id
                )
                nested_states, nested_transitions = self._convert_states_and_notes(
                    comp_doc,
                    all_states,
                    parent_id=comp_state_id,
                    parent_path=new_parent_path,
                )
                states.update(nested_states)
                transitions.extend(nested_transitions)

            # Then process root-level transitions
            level_transitions = self._convert_transitions(
                root_doc, states, all_states, parent_id, parent_path
            )
            transitions.extend(level_transitions)
        else:
            # Non-root level: process transitions first (breadth-first)
            level_transitions = self._convert_transitions(
                root_doc, states, all_states, parent_id, parent_path
            )
            transitions.extend(level_transitions)

            # Then recursively process nested content
            for comp_state_id, comp_doc in composite_states:
                new_parent_path = (
                    f"{parent_path}_{comp_state_id}" if parent_path else comp_state_id
                )
                nested_states, nested_transitions = self._convert_states_and_notes(
                    comp_doc,
                    all_states,
                    parent_id=comp_state_id,
                    parent_path=new_parent_path,
                )
                states.update(nested_states)
                transitions.extend(nested_transitions)

        # PASS 4: Process divider regions (parallel states)
        if divider_regions:
            parallel_info = self._process_parallel_regions(
                divider_regions, all_states, parent_id, parent_path
            )
            # Add the parallel region states and transitions
            for region_data in parallel_info:
                states.update(region_data["states"])
                transitions.extend(region_data["transitions"])

            # Mark the parent state as having parallel regions
            # The parent state is in all_states, not the local states dict
            if parent_id:
                # Find the parent state in all_states (try both scoped and unscoped keys)
                parent_state = all_states.get(parent_id)
                if parent_state is None and parent_path:
                    # Try with full path
                    for key, state in all_states.items():
                        if hasattr(state, "id_") and state.id_ == parent_id:
                            parent_state = state
                            break

                if parent_state:
                    # Add parallel_regions attribute dynamically
                    parent_state.parallel_regions = parallel_info
                    logger.debug(
                        f"Set parallel_regions on {parent_id}: {len(parallel_info)} regions"
                    )

        return states, transitions

    def _create_state(
        self, state_info: dict, parent_id: str = None, scoped_id: str = None
    ) -> State:
        """
        Create a State object from parsed state info.

        Args:
            state_info: Dictionary containing state information
            parent_id: ID of the parent state (if this is a nested state)
            scoped_id: Full scoped identifier for the state (e.g., 'SpaManager_Sauna_Off')

        Returns:
            State, Start, End, Composite, or Concurrent object
        """
        state_id = state_info["id"]
        if "_start" in state_id:
            return Start()
        elif "_end" in state_id:
            return End()
        else:
            # Create state (regular or composite)
            if "doc" in state_info:
                # Composite state - we'll create a regular state for now
                # The nested states will be processed separately
                state = Composite(
                    id_=state_id,
                    content=state_info.get("description", ""),
                    sub_states=[],  # Will be populated during recursive processing
                    transitions=[],
                )
            else:
                # Regular state
                state = State(id_=state_id, content=state_info.get("description", ""))

            state.id_ = state_id

            # Set parent_id if this state is nested
            if parent_id is not None:
                state.parent_id = parent_id

            # Set scoped_id for unique identification across parallel regions
            # This allows disambiguation of states with the same name in different scopes
            state.scoped_id = scoped_id if scoped_id else state_id

            return state

    def _get_scoped_key(self, state_id: str, parent_id: str = None) -> str:
        """
        Generate a scoped key for a state based on its ID and parent context.
        This allows multiple states with the same name in different scopes.

        Args:
            state_id: The state's ID
            parent_id: The parent state's ID (if nested)

        Returns:
            A scoped key for the state
        """
        if parent_id and not ("_start" in state_id or "_end" in state_id):
            return f"{parent_id}_{state_id}"
        return state_id

    def _find_nearest_common_ancestor(self, path1: str, path2: str) -> str:
        """
        Find the nearest common ancestor of two paths.

        Args:
            path1: First hierarchical path (e.g., "On_LoggedOut")
            path2: Second hierarchical path (e.g., "On_LoggedIn_Print")

        Returns:
            The nearest common ancestor path (e.g., "On"), or None if no common ancestor
        """
        if not path1 or not path2:
            return None

        parts1 = path1.split("_")
        parts2 = path2.split("_")

        common = []
        for p1, p2 in zip(parts1, parts2):
            if p1 == p2:
                common.append(p1)
            else:
                break

        return "_".join(common) if common else None

    def _find_state_in_all_states(
        self,
        state_id: str,
        parent_path: str,
        all_states: dict[str, State],
        allow_sibling_search: bool = True,
    ) -> tuple[State, str]:
        """
        Find a state in all_states, checking both scoped and unscoped keys.
        Priority:
        1. Exact scoped key (within current context) - for states defined in this scope
        2. Unscoped key (global/root) - for states defined at root level
        3. Parent scope - for states defined in parent composite state
        4. Sibling scopes (if allow_sibling_search=True) - for states referenced by multiple siblings
        5. Any scope - for cross-scope references (only when searching from root)

        Args:
            state_id: The state's ID
            parent_path: The current parent path (hierarchical path for scoping)
            all_states: Dictionary of all states
            allow_sibling_search: If True, search sibling scopes for cross-scope references.
                                 If False, only search current scope, parent scopes, and root.

        Returns:
            Tuple of (state, key_used) or (None, None) if not found
        """
        # First check if it exists in the current scope with a scoped key
        scoped_key = self._get_scoped_key(state_id, parent_path)
        if scoped_key in all_states:
            return all_states[scoped_key], scoped_key

        # Then check if it exists at unscoped (global/root) level
        # This handles references to root-level states from any scope
        if state_id in all_states:
            return all_states[state_id], state_id

        # Check parent scopes by walking up the hierarchy
        # e.g., if we're in On_LoggedIn_Print and looking for Idle,
        # check if On_LoggedIn_Idle exists
        if parent_path and "_" in parent_path:
            parts = parent_path.split("_")
            for i in range(len(parts), 0, -1):
                parent_prefix = "_".join(parts[:i])
                parent_scoped_key = f"{parent_prefix}_{state_id}"
                if parent_scoped_key in all_states:
                    return all_states[parent_scoped_key], parent_scoped_key

        # Check related scopes - search for this state in ANCESTOR scopes only
        # Only do this if allow_sibling_search is True
        # IMPORTANT: Don't return states from sibling composite states (e.g., Print's Suspended
        # when looking from Scan). Each composite state should have its own local states.
        if allow_sibling_search and parent_path:
            for key, state in all_states.items():
                # Check if this state has matching id_
                if hasattr(state, "id_") and state.id_ == state_id:
                    # Check if this state is in an ancestor scope of the current path
                    # (not a sibling composite state at the same level)
                    # For example, if parent_path is "On_LoggedIn_Scan" and key is "On_LoggedIn_Print_Suspended",
                    # this is NOT an ancestor (it's a sibling), so skip it.
                    # But if key is "On_LoggedIn_Error", it IS in an ancestor scope.
                    state_scope = key.rsplit("_", 1)[0] if "_" in key else ""
                    # State is in ancestor scope if the current path starts with the state's scope
                    # or if the state is at the same level as an ancestor
                    if state_scope and parent_path.startswith(state_scope + "_"):
                        # This state's scope is a prefix of our current path - it's an ancestor
                        return state, key
                    elif not state_scope:
                        # Root level state
                        return state, key

        # If we're at root level (parent_path is None), search all scopes for this state
        # This handles cases where a state is defined in a nested scope but referenced from root
        if parent_path is None:
            for key, state in all_states.items():
                # Check if this key ends with the state_id and the state's id_ matches
                if (
                    (key.endswith(f"_{state_id}") or key == state_id)
                    and hasattr(state, "id_")
                    and state.id_ == state_id
                ):
                    return state, key

        return None, None

    def _convert_transitions(
        self,
        root_doc: list[dict],
        current_states: dict[str, State],
        all_states: dict[str, State],
        parent_id: str = None,
        parent_path: str = None,
    ) -> list[Transition]:
        """
        Convert relation items to Transition objects.

        Args:
            root_doc: List of parsed state diagram elements
            current_states: Dictionary of current states on the current level
            all_states: Dictionary to store all states by id in the state diagram
            parent_id: ID of the parent state (for transitions within a composite state)
            parent_path: Full hierarchical path to parent - used for scoped keys

        Returns:
            List of Transition objects
        """
        # If parent_path is not provided, use parent_id
        if parent_path is None:
            parent_path = parent_id
        transitions = []

        # Process relation items
        for item in root_doc:
            # Skip items that are strings
            if isinstance(item, str):
                continue

            if item["stmt"] == "relation":
                state1_info = item["state1"]
                state2_info = item["state2"]

                # Handle state1
                from_id = state1_info["id"]
                from_state, found_key = self._find_state_in_all_states(
                    from_id, parent_path, all_states
                )

                # If we're at root level and found a state in a nested scope that's the SOURCE of this transition
                # then promote it to root level (it's directly accessible from root)
                if from_state and parent_id is None and found_key and "_" in found_key:
                    # Check if a root-level version already exists
                    if from_id not in all_states:
                        # This state is the source of a root-level transition
                        # Promote it to root level
                        from_state.parent_id = None
                        # Also store it with unscoped key for future lookups
                        all_states[from_id] = from_state
                        # Remove the scoped key to avoid duplication
                        if found_key in all_states:
                            del all_states[found_key]
                    else:
                        # Root version exists, use that instead
                        from_state = all_states[from_id]

                if from_state is None:
                    # This state is being defined for the first time
                    if parent_id and from_id == parent_id:
                        # Self-reference: Don't set parent_id, use unscoped key
                        new_state = self._create_state(
                            state1_info, parent_id=None, scoped_id=from_id
                        )
                        all_states[from_id] = new_state
                        from_state = new_state
                    elif "_start" in from_id or "_end" in from_id:
                        # Start/End states: use scoped key
                        scoped_key = self._get_scoped_key(from_id, parent_path)
                        new_state = self._create_state(
                            state1_info, parent_id, scoped_id=scoped_key
                        )
                        all_states[scoped_key] = new_state
                        from_state = new_state
                    elif parent_id:
                        # New state in this scope: use scoped key
                        scoped_key = self._get_scoped_key(from_id, parent_path)
                        new_state = self._create_state(
                            state1_info, parent_id, scoped_id=scoped_key
                        )
                        all_states[scoped_key] = new_state
                        from_state = new_state
                    else:
                        # Root level state: use unscoped key
                        new_state = self._create_state(
                            state1_info, parent_id=None, scoped_id=from_id
                        )
                        all_states[from_id] = new_state
                        from_state = new_state

                    # Always add the new state to current_states
                    current_states[from_id] = from_state

                # Handle state2
                to_id = state2_info["id"]
                # If this transition starts from a start marker ([*] or _start),
                # the destination should be created in the current scope, not found in siblings
                is_initial_transition = (
                    from_id == "[*]" or "_start" in from_id or from_id == "root_start"
                )
                to_state, found_key = self._find_state_in_all_states(
                    to_id,
                    parent_path,
                    all_states,
                    allow_sibling_search=not is_initial_transition,
                )

                # If we found the state in a different scope, promote it to nearest common ancestor
                if to_state and found_key and parent_path:
                    # Get the current parent of the found state
                    current_parent = getattr(to_state, "parent_id", None)
                    # Calculate paths for comparison
                    current_state_path = (
                        found_key.rsplit("_", 1)[0] if "_" in found_key else None
                    )

                    # If the state is in a different branch of the hierarchy
                    if current_state_path and current_state_path != parent_path:
                        # Find nearest common ancestor
                        common_ancestor = self._find_nearest_common_ancestor(
                            current_state_path, parent_path
                        )

                        if common_ancestor:
                            # Promote the state to the common ancestor
                            # Extract the parent_id from the common ancestor path
                            new_parent_id = (
                                common_ancestor.split("_")[-1]
                                if common_ancestor
                                else None
                            )
                            to_state.parent_id = new_parent_id

                            # Update the key in all_states
                            new_key = self._get_scoped_key(to_id, common_ancestor)
                            if new_key != found_key:
                                # Remove old key, add new key
                                if found_key in all_states:
                                    del all_states[found_key]
                                all_states[new_key] = to_state

                if to_state is None:
                    # This state is being defined for the first time
                    if parent_id and to_id == parent_id:
                        # Self-reference: Don't set parent_id, use unscoped key
                        new_state = self._create_state(
                            state2_info, parent_id=None, scoped_id=to_id
                        )
                        all_states[to_id] = new_state
                        to_state = new_state
                    elif "_start" in to_id or "_end" in to_id:
                        # Start/End states: use scoped key
                        scoped_key = self._get_scoped_key(to_id, parent_path)
                        new_state = self._create_state(
                            state2_info, parent_id, scoped_id=scoped_key
                        )
                        all_states[scoped_key] = new_state
                        to_state = new_state
                    elif parent_id:
                        # New state in this scope: use scoped key
                        scoped_key = self._get_scoped_key(to_id, parent_path)
                        new_state = self._create_state(
                            state2_info, parent_id, scoped_id=scoped_key
                        )
                        all_states[scoped_key] = new_state
                        to_state = new_state
                    else:
                        # Root level state: use unscoped key
                        new_state = self._create_state(
                            state2_info, parent_id=None, scoped_id=to_id
                        )
                        all_states[to_id] = new_state
                        to_state = new_state

                    # Always add the new state to current_states
                    current_states[to_id] = to_state

                # Get transition label if present
                label = item.get("description", "")

                transition = Transition(from_=from_state, to=to_state, label=label)
                transitions.append(transition)

        return transitions

    def _process_parallel_regions(
        self,
        divider_regions: list[dict],
        all_states: dict[str, State],
        parent_id: str = None,
        parent_path: str = None,
    ) -> list[dict]:
        """
        Process divider regions to extract parallel state information.

        Each divider region contains states and transitions that should run
        concurrently with other regions under the same parent.

        Args:
            divider_regions: List of divider items from the parser
            all_states: Dictionary to store all states by id
            parent_id: ID of the parent composite state
            parent_path: Full hierarchical path to parent

        Returns:
            List of region dictionaries, each containing:
            - 'name': Region identifier (e.g., 'region_0', 'region_1')
            - 'states': Dict of states in this region
            - 'transitions': List of transitions in this region
            - 'initial': Initial state ID for this region (if any)
        """
        parallel_info = []

        for idx, divider in enumerate(divider_regions):
            divider_id = divider.get("id", f"region_{idx}")
            divider_doc = divider.get("doc", [])

            # Create a unique region name
            region_name = f"region_{idx}"

            # Process the divider's content using the existing conversion logic
            # Use a modified parent path that includes the region identifier
            region_parent_path = (
                f"{parent_path}_{region_name}" if parent_path else region_name
            )

            region_states, region_transitions = self._convert_states_and_notes(
                divider_doc,
                all_states,
                parent_id=parent_id,  # States belong to the same parent
                parent_path=region_parent_path,
            )

            # Find the initial state for this region
            initial_state = None
            for state_id, state in region_states.items():
                if isinstance(state, Start):
                    # Find what the start state transitions to
                    for trans in region_transitions:
                        if isinstance(trans.from_state, Start):
                            initial_state = (
                                trans.to_state.id_
                                if hasattr(trans.to_state, "id_")
                                else str(trans.to_state)
                            )
                            break
                    break

            parallel_info.append(
                {
                    "name": region_name,
                    "divider_id": divider_id,  # Original divider ID for reference
                    "states": region_states,
                    "transitions": region_transitions,
                    "initial": initial_state,
                }
            )

        return parallel_info

    def _convert_state_diagram(
        self, root_doc: list[dict], all_states: dict[str, State]
    ) -> tuple[list[State], list[Transition]]:
        """
        Convert parsed state diagram data to StateDiagramWithNote object.

        Args:
            root_doc: List of parsed state diagram elements
            all_states: Dictionary to store all states by id

        Returns:
            Tuple of (state_list, transitions)
        """
        # Convert states and transitions (recursively processes composite states)
        states_dict, transitions = self._convert_states_and_notes(root_doc, all_states)

        # Create the state diagram from all_states (which includes both scoped and unscoped states)
        state_list = list(all_states.values())

        return state_list, transitions

    # def to_networkx(self, state_diagram: StateDiagram) -> nx.DiGraph:
    #     G = nx.DiGraph()
    #     for node in state_diagram.nodes.values():
    #         G.add_node(node.id, content=node.content, shape=node.shape)
    #     for link in state_diagram.links:
    #         G.add_edge(
    #             link.origin.id, link.end.id, shape=link.shape, message=link.message
    #         )
    #     return G
