import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph, Namespace, RDF
from owlrl import DeductiveClosure, OWLRL_Semantics

app = FastAPI()

BASE = Namespace("http://example.org/ai-unified-ontology#")
DB_PATH = "project_state.db"

# =========================
# DATABASE LAYER
# =========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS modules (
            module_name TEXT PRIMARY KEY,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_db_status(module_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status FROM modules WHERE module_name=?", (module_name,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_db_status(module_name, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO modules (module_name, status)
        VALUES (?, ?)
        ON CONFLICT(module_name)
        DO UPDATE SET status=excluded.status
    """, (module_name, status))
    conn.commit()
    conn.close()

init_db()

# =========================
# LOAD ONTOLOGY
# =========================

print("Loading ontology...")
g = Graph()
g.parse("ontology/ai_unified_ontology.ttl", format="ttl")

print(f"Original triples: {len(g)}")

print("Running OWL RL reasoning...")
DeductiveClosure(OWLRL_Semantics).expand(g)

print(f"Triples after reasoning: {len(g)}")
print("Ontology ready.")

MCP_PROTOCOL_VERSION = "2025-03-26"

# =========================
# GRAPH HELPERS
# =========================

def get_all_modules():
    return [str(m).split("#")[-1]
            for m in g.subjects(RDF.type, BASE.Module)]

def get_dependencies(module_name):
    module_uri = BASE[module_name]
    return [str(dep).split("#")[-1]
            for _, _, dep in g.triples((module_uri, BASE.dependsOnModule, None))]

def detect_cycles():
    graph = {m: get_dependencies(m) for m in get_all_modules()}
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

def compute_next_steps():
    ready = []
    for m in get_all_modules():
        if get_db_status(m) != "pending":
            continue
        deps = get_dependencies(m)
        if all(get_db_status(d) == "completed" for d in deps):
            ready.append(m)
    return ready

# =========================
# OPERATIONAL CRITICAL PATH (STRICT)
# =========================

def compute_operational_critical_path():

    # Only active (not completed) modules participate
    active_modules = [
        m for m in get_all_modules()
        if get_db_status(m) != "completed"
    ]

    # Build reverse graph dependency → dependent
    graph = {m: [] for m in active_modules}

    for m in active_modules:
        deps = get_dependencies(m)
        for d in deps:
            if d in active_modules:  # ignore completed nodes entirely
                graph[d].append(m)

    memo = {}

    def longest(node):
        if node in memo:
            return memo[node]

        neighbors = graph.get(node, [])

        if not neighbors:
            memo[node] = (1, [node])
            return memo[node]

        max_len = 0
        max_path = []

        for n in neighbors:
            length, path = longest(n)
            if length > max_len:
                max_len = length
                max_path = path

        memo[node] = (max_len + 1, [node] + max_path)
        return memo[node]

    max_overall = (0, [])

    for node in active_modules:
        length, path = longest(node)
        if length > max_overall[0]:
            max_overall = (length, path)

    return {
        "length": max_overall[0],
        "path": max_overall[1]
    }

# =========================
# LIFECYCLE STATE
# =========================

def evaluate_project_state():

    if detect_cycles():
        return "blocked_by_cycle"

    modules = get_all_modules()

    if all(get_db_status(m) == "completed" for m in modules):
        return "completed"

    if compute_next_steps():
        return "active"

    return "stalled"

# =========================
# MCP ENDPOINT
# =========================

@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    method = body.get("method")
    id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "ai-mcp-server",
                    "version": "9.0.0"
                }
            }
        })

    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "tools": [
                    {
                        "name": "update_module_status",
                        "description": "Update module status",
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
                        "description": "Return executable modules",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "detect_dependency_cycles",
                        "description": "Detect circular dependencies",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "compute_operational_critical_path",
                        "description": "Compute longest pending dependency path",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "evaluate_project_state",
                        "description": "Evaluate lifecycle state",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                ]
            }
        })

    if method == "tools/call":
        tool = params.get("name")
        args = params.get("arguments", {})

        if tool == "update_module_status":
            set_db_status(args["module"], args["status"])
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text", "text": "Status updated"}],
                    "isError": False
                }
            })

        if tool == "get_project_next_steps":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text",
                                 "text": str(compute_next_steps())}],
                    "isError": False
                }
            })

        if tool == "detect_dependency_cycles":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text",
                                 "text": str(detect_cycles())}],
                    "isError": False
                }
            })

        if tool == "compute_operational_critical_path":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text",
                                 "text": str(compute_operational_critical_path())}],
                    "isError": False
                }
            })

        if tool == "evaluate_project_state":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text",
                                 "text": evaluate_project_state()}],
                    "isError": False
                }
            })

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": -32601,
            "message": "Method not found"
        }
    })
