import sqlite3
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph, Namespace, RDF
from owlrl import DeductiveClosure, OWLRL_Semantics

# ← חיבור ל-Validator
from quality.structural_validator import structural_validate
from quality.recommendations import generate_recommendations

app = FastAPI(
    servers=[
        {"url": "https://ai-mcp-server-1.onrender.com"}
    ]
)

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
# BOOTSTRAP STATE FROM ONTOLOGY
# =========================

def bootstrap_module_states():
    modules = [
        str(m).split("#")[-1]
        for m in g.subjects(RDF.type, BASE.Module)
    ]

    for module in modules:
        if get_db_status(module) is None:
            print(f"Initializing {module} → pending")
            set_db_status(module, "pending")

bootstrap_module_states()

# =========================
# GRAPH HELPERS
# =========================

def get_all_modules():
    return [
        str(m).split("#")[-1]
        for m in g.subjects(RDF.type, BASE.Module)
    ]

def get_dependencies(module_name):
    module_uri = BASE[module_name]
    return [
        str(dep).split("#")[-1]
        for _, _, dep in g.triples((module_uri, BASE.dependsOnModule, None))
    ]

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
                    "version": "11.0.0"
                }
            }
        })

    # =========================
    # TOOLS LIST
    # =========================

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
                        "name": "get_module_statuses",
                        "description": "List module statuses",
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
                    },
                    {
                        "name": "validate_research_proposal_structural",
                        "description": "Evaluate research proposal quality and return score + recommendations",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "proposal": {"type": "object"}
                            },
                            "required": ["proposal"]
                        }
                    }
                ]
            }
        })

    # =========================
    # TOOLS CALL
    # =========================

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

        if tool == "get_module_statuses":
            snapshot = [
                {"module": m, "status": get_db_status(m)}
                for m in get_all_modules()
            ]
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text", "text": str(snapshot)}],
                    "isError": False
                }
            })

        if tool == "evaluate_project_state":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{"type": "text", "text": evaluate_project_state()}],
                    "isError": False
                }
            })

        if tool == "validate_research_proposal_structural":
            result_obj = structural_validate(args["proposal"])
            recommendations = generate_recommendations(result_obj)

            response_payload = {
                "status": "evaluated",
                "score": result_obj.get("structural_score"),
                "threshold": 0.95,
                "critical_failed": result_obj.get("critical_failed", False),
                "missing_fields": result_obj.get("missing_fields", []),
                "violations": result_obj.get("violations", []),
                "recommendations": recommendations
            }

            return JSONResponse({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(response_payload)
                    }],
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

# =========================
# REST VALIDATION ENDPOINT
# =========================

@app.post("/validate_proposal")
async def validate_proposal(payload: dict):

    proposal = payload.get("proposal", {})

    result_obj = structural_validate(proposal)
    recommendations = generate_recommendations(result_obj)

    return {
        "status": "evaluated",
        "score": result_obj.get("structural_score"),
        "threshold": 0.95,
        "critical_failed": result_obj.get("critical_failed", False),
        "missing_fields": result_obj.get("missing_fields", []),
        "violations": result_obj.get("violations", []),
        "recommendations": recommendations
    }