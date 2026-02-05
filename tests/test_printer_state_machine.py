"""
Test for the printer state machine example.
This test validates that the parser correctly handles complex hierarchical state machines.
"""

from mermaid_parser.converters.state_diagram import StateDiagramConverter


def test_printer_state_machine():
    """Test that the printer state machine is parsed correctly."""

    mermaid_text = """stateDiagram-v2
    [*] --> Off
    Off --> On : masterSwitch

    state On {
        [*] --> LoggedOut
        On --> Off : masterSwitch

        state LoggedOut {
            [*] --> AwaitingLogin
            AwaitingLogin --> LoggedIn : cardTap [authorized]
            AwaitingLogin --> Error : cardTap [!authorized]
        }

        state LoggedIn {
            [*] --> Idle

            Idle --> Print : choosePrint
            Idle --> Scan : chooseScan
            Idle --> LoggedOut : logoff

            state Print {
                [*] --> CheckQueue
                CheckQueue --> Printing : start [queueNotEmpty]
                CheckQueue --> Error : start [queueEmpty]
                Printing --> Idle : complete
                Printing --> Suspended : paperJam
                Printing --> Suspended : outOfPaper
                Printing --> Idle : stop
            }

            state Scan {
                [*] --> CheckFeeder
                CheckFeeder --> Scanning : start [documentDetected]
                CheckFeeder --> Error : start [!documentDetected]
                Scanning --> Idle : complete
                Scanning --> Suspended : paperJam
                Scanning --> Idle : stop
            }

            state Suspended {
                [*] --> AwaitingResolution
                AwaitingResolution --> ResupplyPaper : outOfPaper
                AwaitingResolution --> ClearJam : paperJam
                ResupplyPaper --> Print : resume
                ClearJam --> Print : resume
                ResupplyPaper --> Idle : cancel
                ClearJam --> Idle : cancel
            }
        }
    }"""

    converter = StateDiagramConverter()
    result = converter.convert(mermaid_text)

    # Build a map of states by ID for easy lookup
    states_by_id = {}
    for state in result.states:
        state_id = getattr(state, "id_", None)
        if state_id:
            states_by_id[state_id] = state

    # Expected hierarchical structure
    # NOTE: Error is referenced by LoggedOut, Print, and Scan but NOT explicitly declared anywhere.
    # With the new behavior, implicit states stay where they're first referenced.
    # Error is first referenced in LoggedOut (AwaitingLogin --> Error), so it stays there.
    # Other scopes that reference Error will use the same Error state (no duplicates).
    expected_hierarchy = {
        "On": ["LoggedOut", "LoggedIn"],
        "LoggedOut": ["AwaitingLogin", "Error"],  # Error is first referenced here
        "LoggedIn": ["Idle", "Print", "Scan", "Suspended"],
        "Print": ["CheckQueue", "Printing"],
        "Scan": ["CheckFeeder", "Scanning"],
        "Suspended": ["AwaitingResolution", "ResupplyPaper", "ClearJam"],
    }

    # Test 1: Check that all expected states exist
    expected_states = [
        "Off",
        "On",
        "LoggedOut",
        "AwaitingLogin",
        "LoggedIn",
        "Idle",
        "Print",
        "CheckQueue",
        "Printing",
        "Scan",
        "CheckFeeder",
        "Scanning",
        "Suspended",
        "AwaitingResolution",
        "ResupplyPaper",
        "ClearJam",
        "Error",
    ]

    for state_name in expected_states:
        assert state_name in states_by_id, f"State {state_name} not found"

    # Test 2: Check parent-child relationships
    test_cases = [
        ("Off", None),  # Root level
        ("On", None),  # Root level
        ("LoggedOut", "On"),
        ("AwaitingLogin", "LoggedOut"),
        ("LoggedIn", "On"),
        ("Idle", "LoggedIn"),
        ("Print", "LoggedIn"),
        ("CheckQueue", "Print"),
        ("Printing", "Print"),
        ("Scan", "LoggedIn"),
        ("CheckFeeder", "Scan"),
        ("Scanning", "Scan"),
        ("Suspended", "LoggedIn"),
        ("AwaitingResolution", "Suspended"),
        ("ResupplyPaper", "Suspended"),
        ("ClearJam", "Suspended"),
        (
            "Error",
            "LoggedOut",
        ),  # Error stays where first referenced, not promoted to common ancestor
    ]

    for state_name, expected_parent in test_cases:
        state = states_by_id[state_name]
        actual_parent = getattr(state, "parent_id", None)
        assert (
            actual_parent == expected_parent
        ), f"State {state_name}: expected parent_id={expected_parent}, got {actual_parent}"

    # Test 3: Verify hierarchical structure
    for parent_name, expected_children in expected_hierarchy.items():
        actual_children = [
            s_id
            for s_id, state in states_by_id.items()
            if getattr(state, "parent_id", None) == parent_name
        ]
        assert set(actual_children) == set(
            expected_children
        ), f"Parent {parent_name}: expected children {expected_children}, got {actual_children}"

    # Test 4: Check that there are no duplicate states (excluding start/end markers)
    state_ids = [getattr(s, "id_", None) for s in result.states if hasattr(s, "id_")]
    # Remove start/end markers from count (they're scoped per composite state and not meaningful for evaluation)
    # Start markers: '_start' suffix, '[*]', or 'Start' (from mermaid Start class)
    # End markers: '_end' suffix or '[*]'
    non_marker_ids = [
        sid
        for sid in state_ids
        if sid
        and not sid.endswith("_start")
        and not sid.endswith("_end")
        and sid != "[*]"
        and sid != "Start"  # Filter out Start class instances
    ]
    unique_ids = set(non_marker_ids)
    assert len(non_marker_ids) == len(
        unique_ids
    ), f"Found duplicate states: {[sid for sid in non_marker_ids if non_marker_ids.count(sid) > 1]}"

    # Test 5: Verify transition count
    assert len(result.transitions) > 0, "No transitions found"
