from loguru import logger
from mermaid_parser.structs.state_diagram import (
    ExtendedStateDiagram,
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
        self.state_notes = {}  # Maps state ID -> list of note text strings

    def convert(self, mermaid_text: str) -> ExtendedStateDiagram:
        # Reset history state tracking for each conversion
        self.history_states = {}
        self.history_transitions = {}
        self.state_notes = {}

        # Pre-scan the raw mermaid text to find where each state is declared
        # This solves forward reference issues where states are used before being declared
        self.state_declarations_map = self._prescan_all_state_declarations_from_text(
            mermaid_text
        )

        # TODO: the current parser does not handle rendering styles
        parsed_data = self.parser.parse(mermaid_text)
        graph_type = parsed_data.get("graph_type")
        if "stateDiagram" not in graph_type:
            raise ValueError(f"Unsupported graph type: {graph_type}")

        all_states = {}
        states, transitions = self._convert_state_diagram(
            parsed_data["graph_data"]["rootDoc"], all_states
        )

        # Filter out Start and End pseudo-states from the states list
        # [*] should never appear as a named state - only as an initial marker
        filtered_states = [
            state for state in states if not isinstance(state, (Start, End))
        ]

        # Add history states to the filtered states list
        for history_state in self.history_states.values():
            filtered_states.append(history_state)

        # Extract initial states from transitions
        root_initial_state, initial_states = self._extract_initial_states(transitions)

        # Filter out transitions from/to Start/End pseudo-states
        # These are tracked via root_initial_state and initial_states instead
        # [*] should never appear in regular transitions
        filtered_transitions = [
            trans
            for trans in transitions
            if not isinstance(getattr(trans, "from_state", None), (Start, End))
            and not isinstance(getattr(trans, "to_state", None), (Start, End))
        ]

        result = ExtendedStateDiagram(
            title="State Diagram",
            states=filtered_states,
            transitions=filtered_transitions,
            version="v2",
            root_initial_state=root_initial_state,
            initial_states=initial_states,
            state_notes=self.state_notes,
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

            # Check if this is an initial state transition ([*], _start, or Start class)
            # The Start class has id_='Start', so we need to check for that as well
            if from_id in ["root_start", "[*]", "Start"] or (
                from_id and "_start" in from_id
            ):
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

    def _prescan_state_declarations(
        self,
        root_doc: list,
        all_states: dict[str, State],
        parent_id: str = None,
        parent_path: str = None,
    ):
        """
        Pre-scan state declarations in root_doc and all nested composites.
        This ensures all explicit state declarations are registered before transitions are processed.
        Only creates states, doesn't process transitions.

        Args:
            root_doc: List of parsed elements
            all_states: Dictionary to store states
            parent_id: ID of the parent state
            parent_path: Full hierarchical path to parent
        """
        if parent_path is None:
            parent_path = parent_id

        for item in root_doc:
            # Handle string state declarations
            if isinstance(item, str):
                state_id = item
                scoped_key = self._get_scoped_key(state_id, parent_path)
                if scoped_key not in all_states:
                    state_info = {"id": state_id, "type": "default", "description": ""}
                    state = self._create_state(
                        state_info, parent_id, scoped_id=scoped_key
                    )
                    if state:
                        all_states[scoped_key] = state
                continue

            if item.get("stmt") == "state":
                state_id = item["id"]
                if item.get("type") == "divider":
                    continue

                scoped_key = self._get_scoped_key(state_id, parent_path)
                if scoped_key not in all_states:
                    state = self._create_state(item, parent_id, scoped_id=scoped_key)
                    if state:
                        all_states[scoped_key] = state

                        # If this is a composite state, recursively pre-scan its content
                        if "doc" in item:
                            new_parent_path = (
                                f"{parent_path}_{state_id}" if parent_path else state_id
                            )
                            self._prescan_state_declarations(
                                item["doc"], all_states, state_id, new_parent_path
                            )

    def _prescan_all_state_declarations_from_text(
        self, mermaid_text: str
    ) -> dict[str, str]:
        """
        Pre-scan the raw mermaid text to find where each state is truly declared.
        This solves the forward reference problem where states are used before being declared.

        Returns:
            dict mapping state_id -> parent_id (None = root level)
        """
        state_map = {}  # state_name -> parent_id
        parent_stack = []  # Track nesting as we scan lines

        lines = mermaid_text.split("\n")

        for line in lines:
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith("%%"):
                continue

            # Skip header line
            if "stateDiagram" in stripped:
                continue

            # Entering composite state: "state Active {"
            if stripped.startswith("state ") and "{" in stripped:
                # Extract state name between "state" and "{"
                state_name = stripped.replace("state", "").replace("{", "").strip()
                current_parent = parent_stack[-1] if parent_stack else None
                state_map[state_name] = current_parent
                parent_stack.append(state_name)
                continue

            # Exiting composite state: "}"
            if stripped == "}":
                if parent_stack:
                    parent_stack.pop()
                continue

            # Simple state declaration: "state Completed"
            # Must not have "{" and must start with "state "
            if (
                stripped.startswith("state ")
                and "{" not in stripped
                and "-->" not in stripped
            ):
                # Extract state name after "state"
                state_name = stripped.replace("state", "").strip()
                # Remove any description after the state name
                if " " in state_name:
                    state_name = state_name.split()[0]
                current_parent = parent_stack[-1] if parent_stack else None
                state_map[state_name] = current_parent

        return state_map

    def _convert_states_and_notes(
        self,
        root_doc: list[dict],
        all_states: dict[str, State],
        parent_id: str = None,
        parent_path: str = None,
        is_top_level: bool = True,  # Track if this is the top-level call
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

        # PASS 0: Pre-scan all state declarations recursively (ONLY at top level)
        # This ensures all explicitly declared states in all nested scopes
        # are registered before any transitions are processed
        if is_top_level:
            self._prescan_state_declarations(
                root_doc, all_states, parent_id, parent_path
            )

        # PASS 1: Process state declarations and notes at this level
        for item in root_doc:
            # Handle string state declarations (e.g., "state Idle" becomes just "Idle")
            # These need to be processed BEFORE transitions to ensure proper hierarchy
            if isinstance(item, str):
                state_id = item
                scoped_key = self._get_scoped_key(state_id, parent_path)

                if scoped_key not in all_states:
                    # Create a simple state with proper parent
                    state_info = {"id": state_id, "type": "default", "description": ""}
                    state = self._create_state(
                        state_info, parent_id, scoped_id=scoped_key
                    )
                    if state:
                        states[state_id] = state
                        all_states[scoped_key] = state
                continue

            if item["stmt"] == "state":
                state_id = item["id"]

                # Extract note if present (e.g., entry/exit/do annotations)
                if "note" in item and item["note"]:
                    note_data = item["note"]
                    note_text = (
                        note_data.get("text", "")
                        if isinstance(note_data, dict)
                        else str(note_data)
                    )
                    if note_text:
                        if state_id not in self.state_notes:
                            self.state_notes[state_id] = []
                        self.state_notes[state_id].append(note_text)
                        logger.debug(
                            f"Extracted note for state '{state_id}': {note_text}"
                        )
                    # Note-only items (no doc, no type other than note) can skip state creation
                    # if we only have an id and a note, no doc
                    if "doc" not in item and item.get("type") != "divider":
                        # Still ensure the state exists
                        scoped_key = self._get_scoped_key(state_id, parent_path)
                        if scoped_key not in all_states:
                            state_info = {
                                "id": state_id,
                                "type": "default",
                                "description": "",
                            }
                            state = self._create_state(
                                state_info, parent_id, scoped_id=scoped_key
                            )
                            if state:
                                states[state_id] = state
                                all_states[scoped_key] = state
                        else:
                            states[state_id] = all_states[scoped_key]
                        continue

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
                    # State already exists (created in pre-scan)
                    # Add it to local states dict and check if it's composite
                    state = all_states[scoped_key]
                    states[state_id] = state

                    # Update description if provided
                    description = item.get("description", "")
                    if description:
                        state.content = description

                    # If this is a composite state, save it for later processing
                    if "doc" in item:
                        composite_states.append((state_id, item["doc"]))

        # PASS 2: Process transitions at this level
        # Now transitions can find states declared in nested composites (thanks to PASS 0)
        level_transitions = self._convert_transitions(
            root_doc, states, all_states, parent_id, parent_path
        )
        transitions.extend(level_transitions)

        # PASS 3: Recursively process nested composites (full processing now)
        # This processes nested transitions and further nested composites
        for comp_state_id, comp_doc in composite_states:
            new_parent_path = (
                f"{parent_path}_{comp_state_id}" if parent_path else comp_state_id
            )
            nested_states, nested_transitions = self._convert_states_and_notes(
                comp_doc,
                all_states,
                parent_id=comp_state_id,
                parent_path=new_parent_path,
                is_top_level=False,  # This is not a top-level call
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

    def _find_any_state_by_id(
        self, state_id: str, all_states: dict[str, State]
    ) -> tuple[State, str]:
        """
        Find any state with the given id_ anywhere in all_states.

        This is used to prevent creating duplicate implicit states when the same
        state is referenced from multiple scopes. Unlike _find_state_in_all_states,
        this doesn't check scope hierarchy - it finds ANY state with matching id_.

        Args:
            state_id: The state's ID to find
            all_states: Dictionary of all states by key

        Returns:
            Tuple of (state, key_used) or (None, None) if not found
        """
        # First check exact match (unscoped)
        if state_id in all_states:
            return all_states[state_id], state_id

        # Then search for any state with matching id_
        for key, state in all_states.items():
            if hasattr(state, "id_") and state.id_ == state_id:
                return state, key

        return None, None

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
        4. Child scopes - for states defined in nested composite states (for cross-scope transitions)
        5. Sibling scopes (if allow_sibling_search=True) - for states referenced by multiple siblings

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

        # Check child scopes - DISABLED for now
        # The child scope search was causing issues where states that should be created
        # at the current level were instead being found in child scopes where they
        # happened to be referenced first.
        #
        # For example, if Idle is defined at LoggedIn level but also referenced inside
        # Suspended (a child of LoggedIn), the child scope search would incorrectly
        # find Idle at Suspended level before LoggedIn processed its transitions.
        #
        # TODO: Re-enable child scope search with proper state declaration tracking
        # if parent_path:
        #     search_prefix = f"{parent_path}_"
        #     search_suffix = f"_{state_id}"
        #     for key, state in all_states.items():
        #         if (
        #             key.startswith(search_prefix)
        #             and key.endswith(search_suffix)
        #             and hasattr(state, "id_")
        #             and state.id_ == state_id
        #         ):
        #             return state, key
        # else:
        #     # At root level, search for any key ending with the state_id
        #     search_suffix = f"_{state_id}"
        #     for key, state in all_states.items():
        #         if (
        #             key.endswith(search_suffix)
        #             and hasattr(state, "id_")
        #             and state.id_ == state_id
        #         ):
        #             return state, key

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

                # NOTE: Previous code here would promote states to root level when they're sources
                # of root-level transitions. This has been disabled to preserve hierarchical structure.
                # States should remain in their declared composite parents even if referenced from
                # outside. The transition itself handles the "crossing" of composite boundaries.

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

                # If we found the state in a different scope, DO NOT promote it to nearest common ancestor.
                # In UML state machine semantics, transitioning from outside a composite state
                # to an inner state means "entering" that composite state - the inner state
                # should remain inside its composite parent.
                #
                # The previous behavior was promoting states, which caused states like
                # ScanAndEmail (inside Busy) to be promoted to On when referenced from Ready (inside On).
                # This is incorrect - ScanAndEmail should remain inside Busy.
                #
                # NOTE: This change preserves the original hierarchy as declared in the Mermaid code.
                # Cross-scope transitions simply mean entering/exiting composite states.

                if to_state is None:
                    # Before creating a new state, check if this state exists ANYWHERE else.
                    # This prevents creating duplicate implicit states when the same state
                    # is referenced from multiple scopes (e.g., Error referenced from
                    # LoggedOut, Print, and Scan should be one state, not three).
                    existing_state, existing_key = self._find_any_state_by_id(
                        to_id, all_states
                    )
                    if existing_state is not None:
                        # Use the existing state instead of creating a duplicate
                        to_state = existing_state
                    # This state is being defined for the first time
                    elif parent_id and to_id == parent_id:
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
                        # Check if state is declared elsewhere first
                        if (
                            hasattr(self, "state_declarations_map")
                            and to_id in self.state_declarations_map
                        ):
                            declared_parent = self.state_declarations_map[to_id]
                            if declared_parent is None:
                                # Declared at root level - use unscoped name
                                scoped_key = to_id
                                actual_parent_id = None
                            elif declared_parent != parent_id:
                                # Declared in different parent - use that parent's scope
                                scoped_key = f"{declared_parent}_{to_id}"
                                actual_parent_id = declared_parent
                            else:
                                # Declared in current parent - use current scope
                                scoped_key = self._get_scoped_key(to_id, parent_path)
                                actual_parent_id = parent_id
                        else:
                            # Not found in declarations - create in current scope (fallback)
                            scoped_key = self._get_scoped_key(to_id, parent_path)
                            actual_parent_id = parent_id

                        new_state = self._create_state(
                            state2_info, actual_parent_id, scoped_id=scoped_key
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
        Convert parsed state diagram data to ExtendedStateDiagram object.

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
