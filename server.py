import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph, Namespace, RDF
from owlrl import DeductiveClosure, OWLRL_Semantics

app = FastAPI()

BASE = Namespace("http://example.org/ai-unified-ontology#")
DB_PATH = "project_state.db"
MCP_PROTOCOL_VERSION = "2025-03-26"

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

def get_db_status(module_name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status FROM modules WHERE module_name=?", (module_name,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None  # None means "unknown/unset" in DB

def set_db_status(module_name: str, status: str):
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
# LOAD ONTOLOGY + REASONING
# =========================

print("Loading ontology...")
g = Graph()
g.parse("ontology/ai_unified_ontology.ttl", format="ttl")
print(f"Original triples: {len(g)}")

print("Running OWL RL reasoning...")
DeductiveClosure(OWLRL_Semantics).expand(g)
print(f"Triples after reasoning: {len(g)}")
print("Ontology ready.")

# =========================
# GRAPH HELPERS
# =========================

def get_all_modules():
    # Modules are instances of :Module in the ontology
    return [str(m).split("#")[-1] for m in g.subjects(RDF.type, BASE.Module)]

def get_dependencies(module_name: str):
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
    # Executable = pending AND all deps completed
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
# dependency → dependent, only ACTIVE (not completed)
# =========================

def compute_operational_critical_path():
    active_modules = [m for m in get_all_modules() if get_db_status(m) != "completed"]
    graph = {m: [] for m in active_modules}

    for m in active_modules:
        for d in get_dependencies(m):
            if d in active_modules:  # ignore completed entirely
                graph[d].append(m)

    memo = {}

    def longest(node):
        if node in memo:
            return memo[node]
        neighbors = graph.get(node, [])
        if not neighbors:
            memo[node] = (1, [node])
            return memo[node]
        best_len, best_path = 0, []
        for n in neighbors:
            ln, path = longest(n)
            if ln > best_len:
                best_len, best_path = ln, path
        memo[node] = (best_len + 1, [node] + best_path)
        return memo[node]

    best = (0, [])
    for n in active_modules:
        ln, path = longest(n)
        if ln > best[0]:
            best = (ln, path)

    return {"length": best[0], "path": best[1]}

# =========================
# LIFECYCLE STATE
# =========================

def evaluate_project_state():
    if detect_cycles():
        return "blocked_by_cycle"

    modules = get_all_modules()

    if modules and all(get_db_status(m) == "completed" for m in modules):
        return "completed"

    if compute_next_steps():
        return "active"

    return "stalled"

# =========================
# DIAGNOSIS ENGINE
# =========================

def get_status_snapshot():
    modules = get_all_modules()
    snapshot = []
    for m in sorted(modules):
        st = get_db_status(m)
        snapshot.append({
            "module": m,
            "status": st if st is not None else "unset"
        })
    return snapshot

def diagnose_stall():
    """
    Root-cause analysis for stalled:
    - cycles? (shouldn't be, but we check)
    - any pending modules?
    - for each pending module, which deps block it?
    - if status is unset for some deps, that's a strong culprit.
    """
    state = evaluate_project_state()
    modules = get_all_modules()

    # Edge case: no modules at all
    if not modules:
        return {
            "state": state,
            "summary": "No modules found in ontology.",
            "status_snapshot": [],
            "blocked": [],
            "recommendations": ["Verify ontology has :Module instances."]
        }

    if detect_cycles():
        return {
            "state": "blocked_by_cycle",
            "summary": "Circular dependency detected.",
            "status_snapshot": get_status_snapshot(),
            "blocked": [],
            "recommendations": [
                "Run detect_dependency_cycles and break the loop by removing/adjusting one dependency edge."
            ]
        }

    pending = [m for m in modules if get_db_status(m) == "pending"]
    if not pending:
        # stalled with no pending usually means "unset" statuses or inconsistent DB.
        unset = [m for m in modules if get_db_status(m) is None]
        recs = []
        if unset:
            recs.append("Some module statuses are unset in DB. Set them to pending/completed/inProgress.")
        recs.append("If you expected completion, ensure all modules are marked completed in DB.")
        return {
            "state": state,
            "summary": "No pending modules, but project is not completed. Likely unset statuses.",
            "status_snapshot": get_status_snapshot(),
            "blocked": [],
            "recommendations": recs
        }

    ready = compute_next_steps()
    if ready:
        return {
            "state": "active",
            "summary": "Project is active. Executable modules exist.",
            "status_snapshot": get_status_snapshot(),
            "ready_modules": ready,
            "blocked": [],
            "recommendations": ["Execute one of the ready modules and update its status to completed."]
        }

    # stalled: pending exists but none executable
    blocked_info = []
    recommendations = []
    for m in pending:
        deps = get_dependencies(m)
        blockers = []
        for d in deps:
            d_status = get_db_status(d)
            if d_status != "completed":
                blockers.append({"module": d, "status": d_status if d_status is not None else "unset"})
        if blockers:
            blocked_info.append({
                "pending_module": m,
                "blocked_by": blockers
            })

    # Aggregate top blockers
    blocker_counts = {}
    for item in blocked_info:
        for b in item["blocked_by"]:
            key = (b["module"], b["status"])
            blocker_counts[key] = blocker_counts.get(key, 0) + 1

    top_blockers = sorted(blocker_counts.items(), key=lambda x: x[1], reverse=True)
    if top_blockers:
        # Human-readable recs
        for (mod, st), cnt in top_blockers[:5]:
            if st == "unset":
                recommendations.append(f"Set status for '{mod}' (currently unset) to pending or completed.")
            else:
                recommendations.append(f"'{mod}' is blocking {cnt} module(s). Current status: {st}. Consider completing it or adjusting dependencies.")

    if not recommendations:
        recommendations = ["Review dependency edges; stalled state detected but no explicit blockers found."]

    return {
        "state": "stalled",
        "summary": "Pending modules exist but none are executable (dependencies not satisfied).",
        "status_snapshot": get_status_snapshot(),
        "ready_modules": [],
        "blocked": blocked_info,
        "recommendations": recommendations
    }

# =========================
# MCP RESPONSE HELPERS
# =========================

def ok(id, text):
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": id,
        "result": {"content": [{"type": "text", "text": text}], "isError": False}
    })

def ok_obj(id, obj):
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": id,
        "result": {"content": [{"type": "text", "text": str(obj)}], "isError": False}
    })

def err(id, message, code=-32602):
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": code, "message": message}
    })

# =========================
# MCP ENDPOINT
# =========================

@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-mcp-server", "version": "10.0.0"}
            }
        })

    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "update_module_status",
                        "description": "Update module status in SQLite (pending/completed/inProgress).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "module": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "completed", "inProgress"]}
                            },
                            "required": ["module", "status"]
                        }
                    },
                    {
                        "name": "get_project_next_steps",
                        "description": "Return executable modules (pending + deps completed).",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "detect_dependency_cycles",
                        "description": "Return True/False if circular dependencies exist.",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "compute_operational_critical_path",
                        "description": "Compute strict operational critical path (dependency-first, excludes completed).",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "evaluate_project_state",
                        "description": "Return lifecycle state: completed/active/stalled/blocked_by_cycle.",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "get_module_statuses",
                        "description": "List all modules and their persisted statuses from SQLite.",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "diagnose_stall",
                        "description": "Full diagnosis for stalled/active states: blockers, ready modules, recommendations.",
                        "inputSchema": {"type": "object", "properties": {}}
                    }
                ]
            }
        })

    if method == "tools/call":
        tool = params.get("name")
        args = params.get("arguments", {}) or {}

        if tool == "update_module_status":
            module = args.get("module")
            status = args.get("status")
            if not module or not status:
                return err(req_id, "Missing required arguments: module, status")
            set_db_status(module, status)
            return ok(req_id, "Status updated")

        if tool == "get_project_next_steps":
            return ok_obj(req_id, compute_next_steps())

        if tool == "detect_dependency_cycles":
            return ok_obj(req_id, detect_cycles())

        if tool == "compute_operational_critical_path":
            return ok_obj(req_id, compute_operational_critical_path())

        if tool == "evaluate_project_state":
            return ok(req_id, evaluate_project_state())

        if tool == "get_module_statuses":
            return ok_obj(req_id, get_status_snapshot())

        if tool == "diagnose_stall":
            return ok_obj(req_id, diagnose_stall())

        return err(req_id, f"Unknown tool: {tool}")

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": "Method not found"}
    })
