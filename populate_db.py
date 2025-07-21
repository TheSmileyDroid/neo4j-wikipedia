import os
import time
import re
import requests
from neo4j import Driver, GraphDatabase
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from urllib.parse import unquote

load_dotenv()

# --- Configuration ---
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
WIKI_USER_AGENT = "NEO4J-Wikipedia-Visualizer/1.0 (https://github.com/TheSmileyDroid)"
# --- End Configuration ---

def create_constraints(driver):
    with driver.session() as session:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Page) REQUIRE p.title IS UNIQUE")
    print("Constraint on :Page(title) created.")

def get_in_text_internal_links(title: str) -> tuple[str, list[str], str]:
    """
    Tenta obter os links internos de parágrafos da Wikipédia em pt, depois em en.

    Retorna:
        page_title (str): o título real da página encontrada
        links (List[str]): títulos de páginas linkadas nos parágrafos
        full_url (str): URL da página
    """
    for lang in ["en", "pt"]:
        print(f"Tentando buscar '{title}' em {lang}.wikipedia.org...")
        try:
            url = f"https://{lang}.wikipedia.org/w/api.php"
            params = {
                "action": "parse",
                "page": title,
                "prop": "text",
                "format": "json"
            }
            headers = {"User-Agent": WIKI_USER_AGENT}
            resp = requests.get(url, params=params, headers=headers)
            data = resp.json()

            if "error" in data:
                continue

            html = data["parse"]["text"]["*"]
            soup = BeautifulSoup(html, "html.parser")

            found_links = set()
            for p in soup.find_all("p"):
                for a in p.find_all("a", href=True): # type: ignore
                    href = a["href"] # type: ignore
                    if href.startswith("/wiki/") and ":" not in href: # type: ignore
                        link_title = unquote(href[len("/wiki/"):].replace("_", " ")) # type: ignore
                        found_links.add(link_title)

            real_title = data["parse"]["title"]
            full_url = f"https://{lang}.wikipedia.org/wiki/{real_title.replace(' ', '_')}"
            return real_title, sorted(found_links), full_url

        except Exception as e:
            print(f"Erro ao acessar {lang}.wikipedia.org: {e}")

    raise ValueError(f"Página '{title}' não encontrada nas Wikipédias pt nem en.")

def populate_database(driver: Driver, start_pages, max_depth=2):
    queue = [(page, 0) for page in start_pages]
    visited = set()

    with driver.session() as session:
        print("Checking for already visited nodes in the database...")
        result = session.run("MATCH (n:Page) WHERE n.url IS NOT NULL RETURN n.title")
        titles = result.to_df()
        visited.update(set([title for title in titles["n.title"].unique().tolist()]))
        print("visited nodes found:", len(visited))

    with driver.session() as session:
        print("Checking for pages with pending visits in the database...")
        result = session.run("MATCH (n:Page) WHERE n.url IS NULL RETURN n.title")
        titles = result.to_df()
        queue.extend([(title, 2) for title in titles["n.title"].unique().tolist()])
        print("pending nodes found:", len(titles))

    while queue:
        page_title, depth = queue.pop(0)

        if page_title in visited or depth > max_depth:
            continue

        try:
            real_title, links, full_url = get_in_text_internal_links(page_title)
        except ValueError as e:
            print(e)
            continue

        visited.add(real_title)
        print(f"Processing '{real_title}' at depth {depth}...")

        with driver.session() as session:
            # Merge the page node
            session.run(
                "MERGE (p:Page {title: $title}) SET p.url = $url",
                title=real_title,
                url=full_url
            )

            if page_title != real_title:
                session.run(
                    "MERGE (p:Page {title: $title}) SET p.url = $url",
                    title=page_title,
                    url=full_url
                )
                session.run(
                    """
                    MATCH (a:Page {title: $source_title})
                    MERGE (b:Page {title: $target_title})
                    MERGE (a)-[:ALIAS]->(b)
                    """,
                    source_title=page_title,
                    target_title=real_title,
                )

            for link in links:
                if link not in visited:
                    queue.append((link, depth + 1))

                session.run(
                    """
                    MATCH (a:Page {title: $source_title})
                    MERGE (b:Page {title: $target_title})
                    MERGE (a)-[:LINKS_TO]->(b)
                    """,
                    source_title=real_title,
                    target_title=link,
                )

        time.sleep(0.25)

if __name__ == "__main__":
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        create_constraints(driver)

        start_pages = ["Graph database", "Neo4j", "World Wide Web"]
        populate_database(driver, start_pages, max_depth=20)

        print("\nPopulation complete!")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'driver' in locals() and driver:
            driver.close()
