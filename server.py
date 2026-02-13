from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph, Namespace, URIRef, RDF
from owlrl import DeductiveClosure, OWLRL_Semantics

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

MCP_PROTOCOL_VERSION = "2025-03-26"

def jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}

def jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}

# -------------------------
# Helper functions
# -------------------------

def get_module_status(module_uri):
    for _, _, status in g.triples((module_uri, BASE.hasStatus, None)):
        return status
    return None

def get_dependencies(module_uri):
    return [dep for _, _, dep in g.triples((module_uri, BASE.dependsOnModule, None))]

def build_dependency_graph():
    graph = {}
    for module in g.subjects(RDF.type, BASE.Module):
        deps = get_dependencies(module)
        graph[module] = deps
    return graph

def detect_cycles():
    graph = build_dependency_graph()
    visited = set()
    stack = set()
    cycles = []

    def dfs(node, path):
        if node in stack:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:])
            return
        if node in visited:
            return

        visited.add(node)
        stack.add(node)

        for neighbor in graph.get(node, []):
            dfs(neighbor, path + [neighbor])

        stack.remove(node)

    for node in graph:
        dfs(node, [node])

    return cycles

# -------------------------
# MCP Endpoint
# -------------------------

@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    method = body.get("method")
    id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return JSONResponse(jsonrpc_result(id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "ai-mcp-server",
                "version": "3.0.0"
            }
        }))

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
                    "description": "Return modules ready to execute",
                    "inputSchema": {
                        "type": "object",
                        "properties": {}
                    }
                },
                {
                    "name": "detect_dependency_cycles",
                    "description": "Detect circular dependencies between modules",
                    "inputSchema": {
                        "type": "object",
                        "properties": {}
                    }
                }
            ]
        }))

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        # ---------------------
        # Get Node Relations
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
        # Update Module Status
        # ---------------------
        if tool_name == "update_module_status":
            module_name = args.get("module")
            status_name = args.get("status")

            if not module_name or not status_name:
                return JSONResponse(jsonrpc_error(id, -32602, "Missing arguments"))

            module_uri = BASE[module_name]
            status_uri = BASE[status_name]

            g.remove((module_uri, BASE.hasStatus, None))
            g.add((module_uri, RDF.type, BASE.Module))
            g.add((module_uri, BASE.hasStatus, status_uri))

            return JSONResponse(jsonrpc_result(id, {
                "content": [{
                    "type": "text",
                    "text": f"Module {module_name} updated to {status_name}"
                }],
                "isError": False
            }))

        # ---------------------
        # Detect Cycles
        # ---------------------
        if tool_name == "detect_dependency_cycles":
            cycles = detect_cycles()

            readable = []
            for cycle in cycles:
                readable.append(
                    [str(node).split("#")[-1] for node in cycle]
                )

            return JSONResponse(jsonrpc_result(id, {
                "content": [{
                    "type": "text",
                    "text": str(readable)
                }],
                "isError": False
            }))

        # ---------------------
        # Get Next Steps
        # ---------------------
        if tool_name == "get_project_next_steps":

            if detect_cycles():
                return JSONResponse(jsonrpc_result(id, {
                    "content": [{
                        "type": "text",
                        "text": "Cannot compute next steps: circular dependency detected"
                    }],
                    "isError": True
                }))

            ready_modules = []

            for module in g.subjects(RDF.type, BASE.Module):
                status = get_module_status(module)

                if status != BASE.pending:
                    continue

                deps = get_dependencies(module)
                all_completed = all(get_module_status(dep) == BASE.completed for dep in deps)

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
