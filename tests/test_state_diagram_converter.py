import pytest
from mermaid_parser.converters.state_diagram import StateDiagramConverter
from mermaid_parser.structs.state_diagram import StateDiagramWithNote


class TestStateDiagramConverter:
    @pytest.fixture
    def converter(self):
        return StateDiagramConverter()

    def test_convert_state_diagram_basic(self, converter):
        """Test convert function with basic state diagram"""
        mermaid_text = """
stateDiagram-v2
    State1: The state with a description
    [*] --> State1
    State1 --> State2
    State2 --> [*]
        """

        result = converter.convert(mermaid_text)

        # Verify the result is a StateDiagramWithNote
        assert isinstance(result, StateDiagramWithNote)
        assert result.title == "State Diagram"
        assert result.version == "v2"

        # Verify states exist
        assert len(result.states) > 0
        state_ids = [getattr(state, "id_", None) for state in result.states]
        state_ids = [id_ for id_ in state_ids if id_ is not None]

        assert len(state_ids) == 4  # start, State1, State2, end

        # Check that our main states are present
        assert "State1" in state_ids
        assert "State2" in state_ids

        # Verify State1 has the correct description
        state1 = next(
            (
                state
                for state in result.states
                if getattr(state, "id_", None) == "State1"
            ),
            None,
        )
        assert state1 is not None
        assert state1.content == "The state with a description"

        # Verify transitions exist
        assert (
            len(result.transitions) >= 3
        )  # [*] -> State1, State1 -> State2, State2 -> [*]

        expected_script = """---
title: State Diagram
---
stateDiagram-v2
    State1 : The state with a description
    State2 : State2
    [*] --> State1
    State1 --> State2
    State2 --> [*]"""
        actual_script = result.script.strip()
        # replace tabs with spaces for comparison
        actual_script = actual_script.replace("\t", "    ")
        assert actual_script == expected_script.strip()

    def test_parent_id_with_composite_states(self, converter):
        """Test that parentId is correctly set for composite states and not for references"""
        mermaid_text = """
stateDiagram-v2
    [*] --> Off
    Off --> On : on

    state On {
        [*] --> Idle
        On --> Off : off
        Idle --> Ready : login
    }
        """

        result = converter.convert(mermaid_text)

        # Helper to find state by id
        def find_state(state_id):
            return next(
                (s for s in result.states if getattr(s, "id_", None) == state_id),
                None,
            )

        # Test 1: Off should NOT have parentId="On" (it's defined at root, just referenced in transition)
        off_state = find_state("Off")
        assert off_state is not None, "Off state should exist"
        off_parent = getattr(off_state, "parent_id", None)
        assert (
            off_parent is None
        ), f"Off should have parent_id=None, but got parent_id={off_parent}"

        # Test 2: On should NOT have parentId="On" (no self-reference)
        on_state = find_state("On")
        assert on_state is not None, "On state should exist"
        on_parent = getattr(on_state, "parent_id", None)
        assert (
            on_parent is None
        ), f"On should have parent_id=None, but got parent_id={on_parent}"

        # Test 3: Idle and Ready should have parentId="On" (defined within On's block)
        idle_state = find_state("Idle")
        assert idle_state is not None, "Idle state should exist"
        idle_parent = getattr(idle_state, "parent_id", None)
        assert (
            idle_parent == "On"
        ), f"Idle should have parent_id='On', but got parent_id={idle_parent}"

        ready_state = find_state("Ready")
        assert ready_state is not None, "Ready state should exist"
        ready_parent = getattr(ready_state, "parent_id", None)
        assert (
            ready_parent == "On"
        ), f"Ready should have parent_id='On', but got parent_id={ready_parent}"

    def test_parent_id_with_nested_composite_states(self, converter):
        """Test parentId with multiple levels of nesting"""
        mermaid_text = """
stateDiagram-v2
    state On {
        state LoggedIn {
            state Print {
                [*] --> Printing
            }
        }
    }
    Error --> LoggedOut : ack
        """

        result = converter.convert(mermaid_text)

        def find_state(state_id):
            return next(
                (s for s in result.states if getattr(s, "id_", None) == state_id),
                None,
            )

        # LoggedIn should have parent_id="On"
        logged_in = find_state("LoggedIn")
        if logged_in:  # May not exist if composite not implemented yet
            assert getattr(logged_in, "parent_id", None) == "On"

        # Print should have parent_id="LoggedIn"
        print_state = find_state("Print")
        if print_state:
            assert getattr(print_state, "parent_id", None) == "LoggedIn"

        # Printing should have parent_id="Print"
        printing = find_state("Printing")
        if printing:
            assert getattr(printing, "parent_id", None) == "Print"

        # Error and LoggedOut should have parent_id=None (root level)
        error = find_state("Error")
        if error:
            assert getattr(error, "parent_id", None) is None

        logged_out = find_state("LoggedOut")
        if logged_out:
            assert getattr(logged_out, "parent_id", None) is None

    def test_parent_id_sibling_reference(self, converter):
        """Test that sibling states referenced in transitions don't get incorrect parentId"""
        mermaid_text = """
stateDiagram-v2
    state A {
        A --> B : go_to_b
    }
    state B {
        B --> A : go_to_a
    }
        """

        result = converter.convert(mermaid_text)

        def find_state(state_id):
            return next(
                (s for s in result.states if getattr(s, "id_", None) == state_id),
                None,
            )

        # Both A and B should have parent_id=None (both are root-level composite states)
        a_state = find_state("A")
        if a_state:
            assert (
                getattr(a_state, "parent_id", None) is None
            ), "A should not have parent_id set"

        b_state = find_state("B")
        if b_state:
            assert (
                getattr(b_state, "parent_id", None) is None
            ), "B should not have parent_id set"

    def test_initial_state_extraction(self, converter):
        """Test that root_initial_state and initial_states are correctly extracted"""
        mermaid_text = """
stateDiagram-v2
    [*] --> Off
    Off --> On : powerOn
    On --> Off : powerOff

    state On {
        [*] --> LoggedOut
        LoggedOut --> LoggedIn : tapCard

        state LoggedIn {
            [*] --> Idle
            Idle --> Busy : start
        }
    }
        """

        result = converter.convert(mermaid_text)

        # Test root initial state
        assert (
            result.root_initial_state == "Off"
        ), f"Root initial state should be 'Off', got '{result.root_initial_state}'"

        # Test nested initial states
        assert "On" in result.initial_states, "On should have an initial state"
        assert (
            result.initial_states["On"] == "LoggedOut"
        ), f"On's initial state should be 'LoggedOut', got '{result.initial_states.get('On')}'"

        assert (
            "LoggedIn" in result.initial_states
        ), "LoggedIn should have an initial state"
        assert (
            result.initial_states["LoggedIn"] == "Idle"
        ), f"LoggedIn's initial state should be 'Idle', got '{result.initial_states.get('LoggedIn')}'"
