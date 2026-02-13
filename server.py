from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph, Namespace, URIRef, RDF
from owlrl import DeductiveClosure, OWLRL_Semantics

# --------------------------------
# App Init
# --------------------------------
app = FastAPI()

BASE = Namespace("http://example.org/ai-unified-ontology#")

print("Loading ontology...")
g = Graph()
g.parse("ontology/ai_unified_ontology.ttl", format="ttl")

print(f"Original triples: {len(g)}")

print("Running OWL RL reasoning...")
DeductiveClosure(OWLRL_Semantics).expand(g)

print(f"Triples after reasoning: {len(g)}")
print("Ontology ready.")

# --------------------------------
# MCP Config
# --------------------------------
MCP_PROTOCOL_VERSION = "2025-03-26"

def jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}

def jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}

# --------------------------------
# Helper Functions
# --------------------------------
def get_module_status(module_uri):
    for _, _, status in g.triples((module_uri, BASE.hasStatus, None)):
        return status
    return None

def get_dependencies(module_uri):
    deps = []
    for _, _, dep in g.triples((module_uri, BASE.dependsOnModule, None)):
        deps.append(dep)
    return deps

# --------------------------------
# MCP Endpoint
# --------------------------------
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
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "ai-mcp-server",
                "version": "2.0.0"
            }
        }))

    # -------------------------
    # List Tools
    # -------------------------
    if method == "tools/list":
        return JSONResponse(jsonrpc_result(id, {
            "tools": [
                {
                    "name": "get_node_relations",
                    "description": "Return RDF triples for a node",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "node": {"type": "string"}
                        },
                        "required": ["node"]
                    }
                },
                {
                    "name": "update_module_status",
                    "description": "Update or create a module and set its status",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "module": {"type": "string"},
                            "status": {"type": "string"}
                        },
                        "required": ["module", "status"]
                    }
                },
                {
                    "name": "get_project_next_steps",
                    "description": "Return modules ready to execute (pending with completed dependencies)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {}
                    }
                }
            ]
        }))

    # -------------------------
    # Tool Call
    # -------------------------
    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        # ---------------------
        # 1. Get Node Relations
        # ---------------------
        if tool_name == "get_node_relations":
            node = args.get("node")
            if not node:
                return JSONResponse(jsonrpc_error(id, -32602, "Missing 'node'"))

            results = []
            for s, p, o in g:
                if str(s).endswith(node) or str(o).endswith(node):
                    results.append({
                        "subject": str(s),
                        "predicate": str(p),
                        "object": str(o)
                    })

            return JSONResponse(jsonrpc_result(id, {
                "content": [{"type": "text", "text": str(results)}],
                "isError": False
            }))

        # ---------------------
        # 2. Update Module Status (Dynamic Memory)
        # ---------------------
        if tool_name == "update_module_status":
            module_name = args.get("module")
            status_name = args.get("status")

            if not module_name or not status_name:
                return JSONResponse(jsonrpc_error(id, -32602, "Missing arguments"))

            module_uri = BASE[module_name]
            status_uri = BASE[status_name]

            # remove old status
            g.remove((module_uri, BASE.hasStatus, None))

            # ensure module exists
            g.add((module_uri, RDF.type, BASE.Module))
            g.add((module_uri, BASE.hasStatus, status_uri))

            return JSONResponse(jsonrpc_result(id, {
                "content": [{
                    "type": "text",
                    "text": f"Module {module_name} updated to status {status_name}"
                }],
                "isError": False
            }))

        # ---------------------
        # 3. Get Project Next Steps
        # ---------------------
        if tool_name == "get_project_next_steps":

            ready_modules = []

            for module in g.subjects(RDF.type, BASE.Module):

                status = get_module_status(module)

                if status != BASE.pending:
                    continue

                deps = get_dependencies(module)

                all_completed = True
                for dep in deps:
                    dep_status = get_module_status(dep)
                    if dep_status != BASE.completed:
                        all_completed = False
                        break

                if all_completed:
                    ready_modules.append(str(module).split("#")[-1])

            return JSONResponse(jsonrpc_result(id, {
                "content": [{
                    "type": "text",
                    "text": str(ready_modules)
                }],
                "isError": False
            }))

        return JSONResponse(jsonrpc_error(id, -32602, "Unknown tool"))

    return JSONResponse(jsonrpc_error(id, -32601, "Method not found"))
