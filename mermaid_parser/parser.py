import json
import pythonmonkey as pm
from pydantic import BaseModel

import asyncio
from pathlib import Path

folder = Path(__file__).parent
parse_mermaid_js = pm.require(f"{folder}/js/parser.bundle.js")


async def parse_mermaid_py(src: str):
    # Use top-level await inside this eval call
    s = await parse_mermaid_js(src)
    return json.loads(s)


class MermaidParser(BaseModel):
    def parse(self, mermaid_text: str) -> dict:
        return asyncio.run(parse_mermaid_py(mermaid_text))


# if __name__ == "__main__":
#     mermaid_graph = """
# flowchart TD\nA[Start] --> |Process| B[End]
#     """
#     result = MermaidParser().parse(mermaid_graph)
#     print(result["graph_data"]["edges"])
#     print(result["graph_data"].keys())


if __name__ == "__main__":
    mermaid_graph ="""stateDiagram-v2
    
    state Off
    [*] --> Off
    Off --> On : on
    On --> Off : off
    
    state On {
        state Idle
        [*] --> Idle
        
        Idle --> Idle : login(cardID) [!idAuthorized(cardID)]
        state Ready
        Idle --> Ready : login(cardID) [idAuthorized(cardID)] / {action="none"}

        Ready --> Idle : logoff
        Ready --> Ready : start [action=="scan" && !originalLoaded()]
        Ready --> Ready : start [action=="print" && !documentInQueue()]
        Ready --> Ready : scan / {action="scan"}
        Ready --> Ready : print / {action="print"}
        Ready --> ScanAndEmail : start [action=="scan" && originalLoaded()]
        Ready --> Print : start [action=="print" && documentInQueue()]

        state Busy {

            state ScanAndEmail

            state Print
            
            state HistoryState1
            
            Print --> Suspended : outOfPaper

        }
       
        Busy --> Suspended : jam
        Busy --> Ready : stop
        Busy --> Ready : done

        state Suspended
        Suspended --> Ready : cancel
        Suspended --> HistoryState1 : resume

    }"""
    
    result = MermaidParser().parse(mermaid_graph)
    graph_type = result.get("graph_type")
    print(f"Graph type: {graph_type}")
    print(result["graph_data"]["edges"])
    print(result["graph_data"].keys())
