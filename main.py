
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
ONGDB_URI = os.environ.get("ONGDB_URI", "bolt://localhost:7687")
ONGDB_USER = os.environ.get("ONGDB_USER", "ongdb")
ONGDB_PASSWORD = os.environ.get("ONGDB_PASSWORD", "password")
# --- End Configuration ---

app = FastAPI()

# Allow CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"]
)

try:
    driver = GraphDatabase.driver(ONGDB_URI, auth=(ONGDB_USER, ONGDB_PASSWORD))
except Exception as e:
    print(f"Failed to connect to OngDB: {e}")
    driver = None

@app.get("/api/search")
def search_pages(q: str):
    if not driver:
        raise HTTPException(status_code=503, detail="Database connection not available")

    query = """
    MATCH (p:Page)
    WHERE p.title CONTAINS $query
    RETURN p.title as title
    LIMIT 10
    """
    with driver.session() as session: # type: ignore types of lib are outdated
        result = session.run(query, query=q)
        return [{"title": record["title"]} for record in result]

@app.get("/api/graph")
def get_graph_data(page: str):
    if not driver:
        raise HTTPException(status_code=503, detail="Database connection not available")

    query = """
    MATCH (p:Page {title: $page_title})
    OPTIONAL MATCH (p)-[r:LINKS_TO]->(outgoing)
    OPTIONAL MATCH (incoming)-[s:LINKS_TO]->(p)
    RETURN p, collect(DISTINCT outgoing) as outgoing_links, collect(DISTINCT incoming) as incoming_links
    """
    with driver.session() as session: # type: ignore types of lib are outdated
        result = session.run(query, page_title=page).single()

    if not result:
        raise HTTPException(status_code=404, detail="Page not found")

    nodes = []
    edges = []
    node_ids = set()

    # Process the main page
    main_node = result["p"]
    if main_node.id not in node_ids:
        nodes.append({"id": main_node.id, "label": main_node["title"], "group": 1})
        node_ids.add(main_node.id)

    # Process outgoing links
    for node in result["outgoing_links"]:
        if node.id not in node_ids:
            nodes.append({"id": node.id, "label": node["title"], "group": 2})
            node_ids.add(node.id)
        edges.append({"from": main_node.id, "to": node.id})

    # Process incoming links
    for node in result["incoming_links"]:
        if node.id not in node_ids:
            nodes.append({"id": node.id, "label": node["title"], "group": 3})
            node_ids.add(node.id)
        edges.append({"from": node.id, "to": main_node.id})

    return {"nodes": nodes, "edges": edges}

@app.on_event("shutdown")
def shutdown_event():
    if driver:
        driver.close()
