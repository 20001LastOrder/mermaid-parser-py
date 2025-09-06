import mermaid from "mermaid";

function replacer(key, value) {
  if(value instanceof Map) {
    return Object.fromEntries(value);
  } else {
    return value;
  }
}

if (typeof structuredClone === "undefined") {
  globalThis.structuredClone = (obj) => {
    return JSON.parse(JSON.stringify(obj));
  };
}


export default async function parse_mermaid(text) {
  // const { default: mermaid } = await import("mermaid")
  mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });
  await mermaid.parse(text); // Pre-parse to catch errors early
  const graph = (await mermaid.mermaidAPI.getDiagramFromText(text));

  const result = {
    graph_type: graph.type,
    graph_data: graph.db
  }

  return JSON.stringify(result, replacer);
}

globalThis.parse_mermaid = parse_mermaid;
