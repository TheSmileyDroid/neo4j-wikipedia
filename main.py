
import os
from flask import Flask, render_template, request, jsonify, abort
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
ONGDB_URI = os.environ.get("ONGDB_URI", "bolt://localhost:7687")
ONGDB_USER = os.environ.get("ONGDB_USER", "ongdb")
ONGDB_PASSWORD = os.environ.get("ONGDB_PASSWORD", "password")
# --- End Configuration ---

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True



try:
    driver = GraphDatabase.driver(ONGDB_URI, auth=(ONGDB_USER, ONGDB_PASSWORD))
except Exception as e:
    print(f"Failed to connect to OngDB: {e}")
    driver = None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search")
def search_pages():
    if not driver:
        abort(503, description="Database connection not available")
    q = request.args.get("q", "")
    query = """
    MATCH (p:Page)
    WHERE p.title CONTAINS $query
    RETURN p.title as title
    ORDER BY length(p.title) ASC
    LIMIT 10
    """
    with driver.session() as session: # type: ignore outdated types
        result = session.run(query, query=q)
        return jsonify([{"title": record["title"]} for record in result])

@app.route("/graph")
def get_graph_data():
    if not driver:
        abort(503, description="Database connection not available")
    page = request.args.get("page", "")
    limit = int(request.args.get("limit", 50))
    if not page:
        abort(400, description="Missing 'page' parameter")

    # Ensure limit is within reasonable bounds
    limit = max(10, min(200, limit))

    # Calculate how many outgoing and incoming links to fetch
    outgoing_limit = min(limit // 2, limit - 1)
    incoming_limit = limit - outgoing_limit - 1  # -1 for the main node

    query = """
    MATCH (p:Page {title: $page_title})
    OPTIONAL MATCH (p)-[r:LINKS_TO]->(outgoing)
    OPTIONAL MATCH (incoming)-[s:LINKS_TO]->(p)
    WITH p, collect(DISTINCT outgoing)[..$outgoing_limit] as outgoing_links, collect(DISTINCT incoming)[..$incoming_limit] as incoming_links
    RETURN p, outgoing_links, incoming_links
    """
    with driver.session() as session: # type: ignore outdated types
        result = session.run(query, page_title=page, outgoing_limit=outgoing_limit, incoming_limit=incoming_limit).single()
    if not result:
        abort(404, description="Page not found")
    nodes = []
    edges = []
    node_ids = set()
    main_node = result["p"]
    if main_node.id not in node_ids:
        nodes.append({"id": main_node.id, "label": main_node["title"], "group": 1})
        node_ids.add(main_node.id)
    for node in result["outgoing_links"]:
        if node and node.id not in node_ids:
            nodes.append({"id": node.id, "label": node["title"], "group": 2})
            node_ids.add(node.id)
        if node:
            edges.append({"from": main_node.id, "to": node.id})
    for node in result["incoming_links"]:
        if node and node.id not in node_ids:
            nodes.append({"id": node.id, "label": node["title"], "group": 3})
            node_ids.add(node.id)
        if node:
            edges.append({"from": node.id, "to": main_node.id})

    # Final check to ensure we don't exceed the limit
    if len(nodes) > limit:
        nodes = nodes[:limit]
        node_ids = set(n["id"] for n in nodes)
        edges = [e for e in edges if e["from"] in node_ids and e["to"] in node_ids]

    return jsonify({"nodes": nodes, "edges": edges})


# --- Shortest path endpoint ---
@app.route("/shortest_path")
def shortest_path():
    if not driver:
        abort(503, description="Database connection not available")
    source = request.args.get("source", "")
    target = request.args.get("target", "")
    if not source or not target:
        abort(400, description="Missing 'source' or 'target' parameter")
    undirected = request.args.get("undirected", "0") in ("1", "true", "True")
    if undirected:
        query = """
        MATCH (start:Page {title: $source}), (end:Page {title: $target})
        MATCH path = shortestPath((start)-[:LINKS_TO*..10]-(end))
        RETURN nodes(path) as ns, relationships(path) as rs
        """
    else:
        query = """
        MATCH (start:Page {title: $source}), (end:Page {title: $target})
        MATCH path = shortestPath((start)-[:LINKS_TO*..10]->(end))
        RETURN nodes(path) as ns, relationships(path) as rs
        """
    with driver.session() as session:  # type: ignore
        result = session.run(query, source=source, target=target).single()
    if not result or not result["ns"]:
        abort(404, description="No path found")
    nodes = []
    edges = []
    node_ids = set()
    for node in result["ns"]:
        if node.id not in node_ids:
            nodes.append({"id": node.id, "label": node["title"], "group": 1 if node["title"] in [source, target] else 2})
            node_ids.add(node.id)
    for rel in result["rs"]:
        edges.append({"from": rel.start_node.id, "to": rel.end_node.id})
    return jsonify({"nodes": nodes, "edges": edges})

if __name__ == '__main__':
        app.run(debug=True) # Use app.run() for development
