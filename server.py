from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph, Namespace, RDF
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
# Helper Functions
# -------------------------

def get_module_status(module):
    for _, _, status in g.triples((module, BASE.hasStatus, None)):
        return status
    return None

def get_dependencies(module):
    return [dep for _, _, dep in g.triples((module, BASE.dependsOnModule, None))]

def build_graph():
    graph = {}
    for module in g.subjects(RDF.type, BASE.Module):
        graph[module] = get_dependencies(module)
    return graph

def detect_cycles():
    graph = build_graph()
    visited = set()
    stack = set()

    def dfs(node):
        if node in stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        stack.add(node)
        for neighbor in graph.get(node, []):
            if dfs(neighbor):
                return True
        stack.remove(node)
        return False

    return any(dfs(node) for node in graph)

def compute_critical_path():
    graph = build_graph()
    memo = {}

    def longest_path(node):
        if node in memo:
            return memo[node]
        deps = graph.get(node, [])
        if not deps:
            memo[node] = (1, [node])
            return memo[node]
        max_length = 0
        max_path = []
        for dep in deps:
            length, path = longest_path(dep)
            if length > max_length:
                max_length = length
                max_path = path
        memo[node] = (max_length + 1, [node] + max_path)
        return memo[node]

    max_overall = (0, [])
    for node in graph:
        length, path = longest_path(node)
        if length > max_overall[0]:
            max_overall = (length, path)

    readable = [str(n).split("#")[-1] for n in max_overall[1]]
    return {
        "length": max_overall[0],
        "path": readable
    }

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
                "version": "4.0.0"
            }
        }))

    if method == "tools/list":
        return JSONResponse(jsonrpc_result(id, {
            "tools": [
                {"name": "get_node_relations", "description": "Return RDF triples", "inputSchema": {"type": "object", "properties": {"node": {"type": "string"}}, "required": ["node"]}},
                {"name": "update_module_status", "description": "Update module status", "inputSchema": {"type": "object", "properties": {"module": {"type": "string"}, "status": {"type": "string"}}, "required": ["module", "status"]}},
                {"name": "get_project_next_steps", "description": "Return executable modules", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "detect_dependency_cycles", "description": "Detect cycles", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "compute_critical_path", "description": "Compute longest dependency path", "inputSchema": {"type": "object", "properties": {}}}
            ]
        }))

    if method == "tools/call":
        tool = params.get("name")

        if tool == "compute_critical_path":
            if detect_cycles():
                return JSONResponse(jsonrpc_result(id, {
                    "content": [{"type": "text", "text": "Cannot compute critical path: cycle detected"}],
                    "isError": True
                }))
            result = compute_critical_path()
            return JSONResponse(jsonrpc_result(id, {
                "content": [{"type": "text", "text": str(result)}],
                "isError": False
            }))

        if tool == "detect_dependency_cycles":
            has_cycle = detect_cycles()
            return JSONResponse(jsonrpc_result(id, {
                "content": [{"type": "text", "text": str(has_cycle)}],
                "isError": False
            }))

        if tool == "get_project_next_steps":
            if detect_cycles():
                return JSONResponse(jsonrpc_result(id, {
                    "content": [{"type": "text", "text": "Cannot compute next steps: cycle detected"}],
                    "isError": True
                }))
            ready = []
            for module in g.subjects(RDF.type, BASE.Module):
                status = get_module_status(module)
                if status != BASE.pending:
                    continue
                deps = get_dependencies(module)
                if all(get_module_status(dep) == BASE.completed for dep in deps):
                    ready.append(str(module).split("#")[-1])
            return JSONResponse(jsonrpc_result(id, {
                "content": [{"type": "text", "text": str(ready)}],
                "isError": False
            }))

        if tool == "update_module_status":
            args = params.get("arguments", {})
            module_name = args.get("module")
            status_name = args.get("status")
            module_uri = BASE[module_name]
            status_uri = BASE[status_name]
            g.remove((module_uri, BASE.hasStatus, None))
            g.add((module_uri, RDF.type, BASE.Module))
            g.add((module_uri, BASE.hasStatus, status_uri))
            return JSONResponse(jsonrpc_result(id, {
                "content": [{"type": "text", "text": f"{module_name} updated to {status_name}"}],
                "isError": False
            }))

        if tool == "get_node_relations":
            args = params.get("arguments", {})
            node = args.get("node")
            results = []
            for s, p, o in g:
                if str(s).endswith(node) or str(o).endswith(node):
                    results.append({"subject": str(s), "predicate": str(p), "object": str(o)})
            return JSONResponse(jsonrpc_result(id, {
                "content": [{"type": "text", "text": str(results)}],
                "isError": False
            }))

        return JSONResponse(jsonrpc_error(id, -32602, "Unknown tool"))

    return JSONResponse(jsonrpc_error(id, -32601, "Method not found"))
