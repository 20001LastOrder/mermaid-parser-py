from mermaid_parser.converters.state_diagram import StateDiagramConverter

mermaid_text = """stateDiagram-v2
    [*] --> Off
    Off --> On : masterSwitch

    state On {
        [*] --> LoggedOut
        On --> Off : masterSwitch

        state LoggedOut {
            [*] --> AwaitingLogin
            AwaitingLogin --> LoggedIn : cardTap [authorized]
            AwaitingLogin --> Error : cardTap [not_authorized]
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
                CheckFeeder --> Error : start [not_documentDetected]
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

# Check where Error ended up
print("Checking Error state:")
for state in result.states:
    if getattr(state, "id_", None) == "Error":
        print(
            f'  Error state: id={state.id_}, parent_id={getattr(state, "parent_id", None)}'
        )

# Check Idle states
print("\nChecking Idle state(s):")
for state in result.states:
    if getattr(state, "id_", None) == "Idle":
        print(
            f'  Idle state: id={state.id_}, parent_id={getattr(state, "parent_id", None)}, scoped_id={getattr(state, "scoped_id", None)}'
        )

# Also check hierarchy
hierarchy = {}
for state in result.states:
    parent = getattr(state, "parent_id", None)
    state_id = getattr(state, "id_", None)
    if parent:
        if parent not in hierarchy:
            hierarchy[parent] = []
        hierarchy[parent].append(state_id)

print("\nHierarchical Structure:")
print(hierarchy)
