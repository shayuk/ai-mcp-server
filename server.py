from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph

app = FastAPI()

g = Graph()
g.parse("ontology/ai_unified_ontology.ttl", format="ttl")

MCP_PROTOCOL_VERSION = "2025-03-26"

def jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}

def jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}

@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    method = body.get("method")
    id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return JSONResponse(jsonrpc_result(id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
                "logging": {}
            },
            "serverInfo": {
                "name": "ai-mcp-server",
                "version": "1.0.0"
            }
        }))

    if method == "tools/list":
        return JSONResponse(jsonrpc_result(id, {
            "tools": [{
                "name": "get_node_relations",
                "description": "Return RDF triples for a node",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "node": {"type": "string"}
                    },
                    "required": ["node"]
                }
            }]
        }))

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "get_node_relations":
            node = args.get("node")
            results = []
            for s, p, o in g:
                if str(s).endswith(node) or str(o).endswith(node):
                    results.append({
                        "subject": str(s),
                        "predicate": str(p),
                        "object": str(o)
                    })

            return JSONResponse(jsonrpc_result(id, {
                "content": [{
                    "type": "text",
                    "text": str(results)
                }],
                "isError": False
            }))

    return JSONResponse(jsonrpc_error(id, -32601, "Method not found"))
