from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph

app = FastAPI()

# Load ontology (make sure the path matches your repo)
g = Graph()
g.parse("ontology/ai_unified_ontology.ttl", format="ttl")

SERVER_NAME = "ai-mcp-server"
SERVER_VERSION = "0.1.0"
MCP_PROTOCOL_VERSION = "2025-03-26"  # MCP spec revision we support


def jsonrpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(request_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def get_relations(node: str):
    if not node:
        return []
    results = []
    for subj, pred, obj in g:
        if str(subj).endswith(node) or str(obj).endswith(node):
            results.append(
                {"subject": str(subj), "predicate": str(pred), "object": str(obj)}
            )
    return results


@app.get("/")
def health():
    return {"status": "ok", "service": SERVER_NAME}


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    payload = await request.json()

    method = payload.get("method")
    params = payload.get("params") or {}
    request_id = payload.get("id")  # may be None for notifications

    # -------------------------
    # MCP handshake: initialize
    # -------------------------
    if method == "initialize":
        client_protocol = params.get("protocolVersion")

        # If client sends a version we don't support, return an MCP-style JSON-RPC error
        # Spec: server can respond with another supported version.
        # We'll always respond with MCP_PROTOCOL_VERSION.
        result = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "This server exposes ontology tools over MCP. "
                "Use tools/list to discover tools and tools/call to invoke them."
            ),
        }
        return JSONResponse(jsonrpc_result(request_id, result))

    # Client sends this as a notification after init; no id => no response required
    if method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "result": True})

    # -------------------------
    # MCP tools: list + call
    # -------------------------
    if method == "tools/list":
        # Minimal tool catalog
        tools = [
            {
                "name": "get_node_relations",
                "description": "Return all RDF triples where a node is subject or object (by local name suffix match).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "node": {"type": "string", "description": "Node local name, e.g., DevOps"}
                    },
                    "required": ["node"],
                },
            },
        ]

        result = {"tools": tools, "nextCursor": None}
        return JSONResponse(jsonrpc_result(request_id, result))

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments") or {}

        if tool_name == "get_node_relations":
            node = args.get("node", "")
            triples = get_relations(node)

            # Tool result per MCP spec: content[] and isError
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"Found {len(triples)} triples for node '{node}'.",
                    },
                    {
                        "type": "text",
                        "text": str(triples),
                    },
                ],
                "isError": False,
            }
            return JSONResponse(jsonrpc_result(request_id, result))

        return JSONResponse(
            jsonrpc_error(request_id, -32602, f"Unknown tool: {tool_name}")
        )

    # -------------------------
    # Unknown method
    # -------------------------
    return JSONResponse(jsonrpc_error(request_id, -32601, "Method not found"))
