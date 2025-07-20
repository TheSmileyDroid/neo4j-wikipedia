import os
from flask import Flask, render_template, request, jsonify, abort
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
# --- End Configuration ---

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True



try:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
except Exception as e:
    print(f"Failed to connect to NEO4J: {e}")
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
    WHERE p.title CONTAINS $q
    RETURN p.title as title, p.url as url
    ORDER BY size(p.title) ASC
    LIMIT 10
    """
    with driver.session() as session: # type: ignore outdated types
        result = session.run(query, q=q)
        return jsonify([{"title": record["title"], "url": record["url"]} for record in result])

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

# --- Demo Queries Endpoints ---
@app.route("/query/page_details")
def get_page_details():
    if not driver:
        abort(503, description="Database connection not available")
    title = request.args.get("title", "")
    if not title:
        abort(400, description="Missing 'title' parameter")

    query = """
    MATCH (p:Page {title: $title})
    RETURN p.title, p.summary, p.url
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, title=title).single()
    if not result:
        abort(404, description="Page not found")
    return jsonify({
        "title": result["p.title"],
        "summary": result["p.summary"],
        "url": result["p.url"]
    })

@app.route("/query/links_from_page")
def get_links_from_page():
    if not driver:
        abort(503, description="Database connection not available")
    title = request.args.get("title", "")
    limit = int(request.args.get("limit", 20))
    if not title:
        abort(400, description="Missing 'title' parameter")

    query = """
    MATCH (p:Page {title: $title})-[:LINKS_TO]->(linkedPage)
    RETURN linkedPage.title
    LIMIT $limit
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, title=title, limit=limit)
        return jsonify([{"title": record["linkedPage.title"]} for record in result])

@app.route("/query/most_referenced")
def get_most_referenced():
    if not driver:
        abort(503, description="Database connection not available")
    limit = int(request.args.get("limit", 10))

    query = """
    MATCH (p:Page)<-[:LINKS_TO]-()
    RETURN p.title, p.url, count(*) AS incoming_links
    ORDER BY incoming_links DESC
    LIMIT $limit
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, limit=limit)
        return jsonify([{
            "title": record["p.title"],
            "url": record["p.url"],
            "incoming_links": record["incoming_links"]
        } for record in result])

@app.route("/query/hub_pages")
def get_hub_pages():
    if not driver:
        abort(503, description="Database connection not available")
    limit = int(request.args.get("limit", 10))

    query = """
    MATCH (p:Page)-[:LINKS_TO]->()
    RETURN p.title, p.url, count(*) AS outgoing_links
    ORDER BY outgoing_links DESC
    LIMIT $limit
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, limit=limit)
        return jsonify([{
            "title": record["p.title"],
            "url": record["p.url"],
            "outgoing_links": record["outgoing_links"]
        } for record in result])

@app.route("/query/mutual_links")
def get_mutual_links():
    if not driver:
        abort(503, description="Database connection not available")
    limit = int(request.args.get("limit", 20))

    query = """
    MATCH (p1:Page)-[:LINKS_TO]->(p2:Page)
    WHERE (p2)-[:LINKS_TO]->(p1)
    RETURN p1.title, p1.url, p2.title, p2.url
    LIMIT $limit
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, limit=limit)
        return jsonify([{
            "page1": record["p1.title"],
            "page1_url": record["p1.url"],
            "page2": record["p2.title"],
            "page2_url": record["p2.url"]
        } for record in result])

@app.route("/query/triangles")
def get_triangles():
    if not driver:
        abort(503, description="Database connection not available")
    limit = int(request.args.get("limit", 10))

    query = """
    MATCH (a:Page)-[:LINKS_TO]->(b:Page)-[:LINKS_TO]->(c:Page)-[:LINKS_TO]->(a)
    RETURN a.title, a.url, b.title, b.url, c.title, c.url
    LIMIT $limit
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, limit=limit)
        return jsonify([{
            "page_a": record["a.title"],
            "page_a_url": record["a.url"],
            "page_b": record["b.title"],
            "page_b_url": record["b.url"],
            "page_c": record["c.title"],
            "page_c_url": record["c.url"]
        } for record in result])

@app.route("/query/neighborhood")
def get_neighborhood():
    if not driver:
        abort(503, description="Database connection not available")
    title = request.args.get("title", "")
    hops = int(request.args.get("hops", 2))
    limit = int(request.args.get("limit", 50))
    if not title:
        abort(400, description="Missing 'title' parameter")

    query = f"""
    MATCH (start:Page {{title: $title}})-[:LINKS_TO*1..{hops}]->(neighbor)
    RETURN DISTINCT neighbor.title, neighbor.url
    LIMIT $limit
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, title=title, limit=limit) # type: ignore
        return jsonify([{"title": record["neighbor.title"], "url": record["neighbor.url"]} for record in result])

@app.route("/query/database_nosql")
def get_database_nosql():
    if not driver:
        abort(503, description="Database connection not available")
    limit = int(request.args.get("limit", 20))

    query = """
    MATCH (db:Page)
    WHERE db.title CONTAINS "database" AND NOT (db)-[:LINKS_TO]->(:Page {title: "SQL"}) AND db.url IS NOT NULL
    RETURN db.title, db.url
    LIMIT $limit
    """
    with driver.session() as session:  # type: ignore
        result = session.run(query, limit=limit)
        return jsonify([{"title": record["db.title"], "url": record["db.url"]} for record in result])

@app.route("/query/execute_custom")
def execute_custom_query():
    if not driver:
        abort(503, description="Database connection not available")
    cypher = request.args.get("cypher", "")
    if not cypher:
        abort(400, description="Missing 'cypher' parameter")

    # Basic security check - only allow READ operations
    cypher_upper = cypher.upper().strip()
    if not cypher_upper.startswith(('MATCH', 'WITH', 'RETURN', 'OPTIONAL')):
        abort(400, description="Only read-only queries are allowed")

    try:
        with driver.session() as session:
            result = session.run(cypher) # type: ignore
            records = []
            for record in result:
                records.append(dict(record))
            return jsonify({"records": records})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == '__main__':
        app.run(debug=True) # Use app.run() for development
