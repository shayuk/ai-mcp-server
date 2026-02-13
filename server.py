from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph
from owlrl import DeductiveClosure, OWLRL_Semantics

# -----------------------------
# App init
# -----------------------------
app = FastAPI()

# -----------------------------
# Load ontology + run reasoning
# -----------------------------
print("Loading ontology...")

g = Graph()
g.parse("ontology/ai_unified_ontology.ttl", format="ttl")

print(f"Original triples: {len(g)}")

print("Running OWL RL reasoning...")
DeductiveClosure(OWLRL_Semantics).expand(g)

print(f"Triples after reasoning: {len(g)}")
print("Ontology ready.")

# -----------------------------
# MCP Config
# -----------------------------
MCP_PROTOCOL_VERSION = "2025-03-26"

def jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}

def jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}

# -----------------------------
# MCP Endpoint
# -----------------------------
@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()

    method = body.get("method")
    id = body.get("id")
    params = body.get("params", {})

    # -------------------------
    # Initialize
    # -------------------------
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
                "version": "1.1.0"
            }
        }))

    # -------------------------
    # List tools
    # -------------------------
    if method == "tools/list":
        return JSONResponse(jsonrpc_result(id, {
            "tools": [{
                "name": "get_node_relations",
                "description": "Return RDF triples for a node (including inferred triples)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "node": {
                            "type": "string",
                            "description": "Local name of the node (e.g., DevOps)"
                        }
                    },
                    "required": ["node"]
                }
            }]
        }))

    # -------------------------
    # Call tool
    # -------------------------
    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "get_node_relations":

            node = args.get("node")

            # 🔒 Validation fix
            if not node:
                return JSONResponse(
                    jsonrpc_error(id, -32602, "Missing required argument: 'node'")
                )

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

        return JSONResponse(
            jsonrpc_error(id, -32602, f"Unknown tool: {tool_name}")
        )

    # -------------------------
    # Unknown method
    # -------------------------
    return JSONResponse(
        jsonrpc_error(id, -32601, "Method not found")
    )
