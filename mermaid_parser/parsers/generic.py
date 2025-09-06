import json
import pythonmonkey as pm
from pydantic import BaseModel

import asyncio
from pathlib import Path

folder = Path(__file__).parent.parent
parse_mermaid_js = pm.require(f"{folder}/js/parser.bundle.js")


async def parse_mermaid_py(src: str):
    # Use top-level await inside this eval call
    s = await parse_mermaid_js(src)
    return json.loads(s)


class MermaidParser(BaseModel):
    def parse(self, mermaid_text: str) -> dict:
        return asyncio.run(parse_mermaid_py(mermaid_text))


if __name__ == "__main__":
    mermaid_graph = """
    graph TD
        StartNode --> DetectIncident["Detect incident"]
        DetectIncident --> CheckFinancialImpact{"Check financial impact?"}
        CheckFinancialImpact -->|No| EndNode["End process"]
        CheckFinancialImpact -->|Yes| OpenEMS["Open EMS"]
        OpenEMS --> ContactApp["Contact Application Team"]
        ContactApp --> ContactSA["Contact SA Team"]
        ContactSA --> ContactDBA["Contact DBA Team"]
        ContactDBA --> OpenConference["Open conference line"]
        OpenConference --> Troubleshoot["Troubleshoot the issue"]
        Troubleshoot --> CheckResolution{"Check if resolution is known?"}
        
        CheckResolution -->|Yes| FixIssue["Fix the issue"]
        FixIssue --> ResolveEMS["Resolve and close EMS"] --> EndNode
        
        CheckResolution -->|No| CheckVendor{"Check vendor for fix?"}
        CheckVendor -->|Yes| FixVendor["Fix the issue (vendor fix)"] --> ResolveEMS
        CheckVendor -->|No| Failover["Failover to COB"] --> ResolveEMS
    """
    result = MermaidParser().parse(mermaid_graph)
    print(result.keys())
    print(result["graph_type"])
