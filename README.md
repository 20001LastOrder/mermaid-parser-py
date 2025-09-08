# mermaid-py-parser
Parse a mermaid text into editable objects. 

**Repository link**: [20001LastOrder/mermaid-parser-py](https://github.com/20001LastOrder/mermaid-parser-py)

## Motivation

I love Mermaid syntax for it's simplicity and expressiveness in creating diagrams. And I use them in a couple of my projects. However, I found that the lack of a robust Python library for parsing and manipulating Mermaid diagrams was a significant limitation.

This library packages the original JS Mermaid parser and ported it with `PythonMonkey` so that the parser can be used in Python. As a result, it can parse _almost any mermaid code into structured JSON object_. I also plan to continue add converting into `mermaid-py` objects and `NertworkX` for eaiser editing and analysis.


## Installation

You can install the library using pip:

```bash
pip install mermaid-parser-py
```

Or install from source:

```bash
poetry install
```

If you want to rebuild the MermaidJS package, you can run the following:
```bash
cd mermaid_parser/js
npm install
npx rollup -c
```

## Basic Usage
### Converting Any Mermaid Code Into JSON

```python
from mermaid_parser import MermaidParser

parser = MermaidParser()
json_output = parser.parse("graph TD; A-->B; A-->C; B-->D; C-->D;")
print(json_output)
```

### Converting FlowChart to Mermaid-Py
```python
from mermaid_parser import FlowChartConverter

converter = FlowChartConverter()
flowchart = converter.convert("flowchart TD\nA[Start] --> |Process| B[End]")
print(flowchart)
```


## Known Limitation
To get the internal representation of Mermaid Diagrams, it uses the _deprecated_ `mermaidAPI` object, which may not be available in future versions of Mermaid.

The MermaidJS diagram does not directly work with serverside Node applications. To make it work, I had to hot-patch the MermaidJS pakcage during packaging time to modify the parts using browser features. See `mermaid_parser/js/rollup.config.mjs` for more details.

## Contribution
Any suggestions, issues, or pull requests are more than welcome 🤗!