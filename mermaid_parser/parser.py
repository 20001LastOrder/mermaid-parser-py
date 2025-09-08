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


if __name__ == "__main__":
    mermaid_graph = """
flowchart TD\nA[Start] --> |Process| B[End]
    """
    result = MermaidParser().parse(mermaid_graph)
    print(result["graph_data"]["edges"])
    print(result["graph_data"].keys())
