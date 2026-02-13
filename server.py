from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from rdflib import Graph

app = FastAPI()

# Load ontology
g = Graph()
g.parse("ontology/ai_unified_ontology.ttl", format="ttl")


def get_relations(node):
    results = []
    for subj, pred, obj in g:
        if str(subj).endswith(node) or str(obj).endswith(node):
            results.append({
                "subject": str(subj),
                "predicate": str(pred),
                "object": str(obj)
            })
    return results


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    data = await request.json()

    method = data.get("method")
    params = data.get("params", {})
    request_id = data.get("id")

    if method == "getNodeRelations":
        node = params.get("node")
        result = get_relations(node)
    else:
        result = {"error": "Unknown method"}

    return JSONResponse({
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id
    })
