import sqlite3
import json
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from rdflib import Graph, Namespace, RDF
from owlrl import DeductiveClosure, OWLRL_Semantics

# =========================
# CONFIG
# =========================

MCP_PROTOCOL_VERSION = "2025-03-26"
DB_PATH = "project_state.db"
BASE = Namespace("http://example.org/ai-unified-ontology#")

app = FastAPI(
    servers=[{"url": "https://ai-mcp-server.onrender.com"}]
)

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

print("Running OWL RL reasoning...")
DeductiveClosure(OWLRL_Semantics).expand(g)
print(f"Ontology ready. Triples count: {len(g)}")

# =========================
# GRAPH HELPERS
# =========================

def get_node_relations(node_name):
    results = []
    for s, p, o in g:
        if str(s).endswith(node_name) or str(o).endswith(node_name):
            results.append({
                "subject": str(s),
                "predicate": str(p),
                "object": str(o)
            })
    return results

def get_dependencies(module_name):
    module_uri = BASE[module_name]
    return [
        str(dep).split("#")[-1]
        for _, _, dep in g.triples((module_uri, BASE.dependsOnModule, None))
    ]

def get_transitive_dependencies(module_name, visited=None):
    if visited is None:
        visited = set()

    deps = get_dependencies(module_name)
    all_deps = []

    for dep in deps:
        if dep not in visited:
            visited.add(dep)
            all_deps.append(dep)
            all_deps.extend(get_transitive_dependencies(dep, visited))

    return list(set(all_deps))

def get_all_modules():
    return [
        str(m).split("#")[-1]
        for m in g.subjects(RDF.type, BASE.Module)
    ]

# =========================
# LIFECYCLE LOGIC
# =========================

def evaluate_project_state():
    modules = get_all_modules()

    if all(get_db_status(m) == "completed" for m in modules):
        return "completed"

    for m in modules:
        if get_db_status(m) == "pending":
            return "active"

    return "stalled"

# =========================
# TOOL ROUTER
# =========================

def handle_tool_call(tool, args, id):

    # ===== ONTOLOGY MODULE =====
    if tool == "get_node_relations":
        node = args.get("node")
        data = get_node_relations(node)
        return tool_success(id, data)

    if tool == "get_dependencies":
        module = args.get("module")
        data = get_dependencies(module)
        return tool_success(id, data)

    if tool == "get_transitive_dependencies":
        module = args.get("module")
        data = get_transitive_dependencies(module)
        return tool_success(id, data)

    # ===== LIFECYCLE MODULE =====
    if tool == "update_module_status":
        set_db_status(args["module"], args["status"])
        return tool_success(id, {"status": "updated"})

    if tool == "get_module_statuses":
        modules = get_all_modules()
        statuses = {m: get_db_status(m) for m in modules}
        return tool_success(id, statuses)

    if tool == "evaluate_project_state":
        state = evaluate_project_state()
        return tool_success(id, {"project_state": state})

    return tool_error(id, "Tool not found")

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
                    "version": "12.0.0"
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
                        "name": "get_node_relations",
                        "description": "Return RDF triples for a node",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"node": {"type": "string"}},
                            "required": ["node"]
                        }
                    },
                    {
                        "name": "get_dependencies",
                        "description": "Return direct dependencies of a module",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"module": {"type": "string"}},
                            "required": ["module"]
                        }
                    },
                    {
                        "name": "get_transitive_dependencies",
                        "description": "Return multi-hop dependencies",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"module": {"type": "string"}},
                            "required": ["module"]
                        }
                    },
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
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "evaluate_project_state",
                        "description": "Evaluate lifecycle state",
                        "inputSchema": {"type": "object", "properties": {}}
                    }
                ]
            }
        })

    if method == "tools/call":
        tool = params.get("name")
        args = params.get("arguments", {})
        return JSONResponse(handle_tool_call(tool, args, id))

    return JSONResponse(tool_error(id, "Method not found"))

# =========================
# HELPERS
# =========================

def tool_success(id, payload):
    return {
        "jsonrpc": "2.0",
        "id": id,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(payload)
            }],
            "isError": False
        }
    }

def tool_error(id, message):
    return {
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": -32601,
            "message": message
        }
    }