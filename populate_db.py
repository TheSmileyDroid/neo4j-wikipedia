

import os
import time
import wikipediaapi
from neo4j import Driver, GraphDatabase
from dotenv import load_dotenv
load_dotenv()

# --- Configuration ---
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
WIKI_LANGUAGE = "pt"
WIKI_USER_AGENT = "NEO4J-Wikipedia-Visualizer/1.0 (https://github.com/TheSmileyDroid)"
# --- End Configuration ---

def create_constraints(driver):
    """
    Ensures the database has the correct constraints for efficient operation.
    """
    with driver.session() as session:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Page) REQUIRE p.title IS UNIQUE")
    print("Constraint on :Page(title) created.")

def populate_database(driver: Driver, start_pages, max_depth=2):
    """
    Crawls Wikipedia from a set of start pages and populates the NEO4J database.
    """
    wiki_api = wikipediaapi.Wikipedia(WIKI_LANGUAGE, headers={"User-Agent": WIKI_USER_AGENT})

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
        queue.extend([(title,2) for title in titles["n.title"].unique().tolist()])
        print("pending nodes found:", len(titles))

    while queue:
        page_title, depth = queue.pop(0)

        if page_title in visited or depth > max_depth:
            continue

        page = wiki_api.page(page_title)

        if not page.exists():
            print(f"Page '{page_title}' not found on Wikipedia. Skipping.")
            continue

        visited.add(page_title)
        print(f"Processing '{page_title}' at depth {depth}...")

        with driver.session() as session:
            # Merge the page node
            session.run(
                "MERGE (p:Page {title: $title}) SET p.summary = $summary, p.url = $url",
                title=page.title,
                summary=page.summary[0:500],  # Truncate summary
                url=page.fullurl,
            )

            if page_title is not page.title:
                session.run(
                    "MERGE (p:Page {title: $title}) SET p.summary = $summary, p.url = $url",
                    title=page_title,
                    summary=page.summary[0:500],
                    url=page.fullurl,
                )

                session.run(
                    """
                    MATCH (a:Page {title: $source_title})
                    MERGE (b:Page {title: $target_title})
                    MERGE (a)-[:ALIAS]->(b)
                    """,
                    source_title=page_title,
                    target_title=page.title,
                )

            # Process links
            for link in page.links:
                if link not in visited:
                    queue.append((link, depth + 1))

                # Merge the linked page and the relationship
                session.run(
                    """
                    MATCH (a:Page {title: $source_title})
                    MERGE (b:Page {title: $target_title})
                    MERGE (a)-[:LINKS_TO]->(b)
                    """,
                    source_title=page.title,
                    target_title=link,
                )

        # Be respectful to the Wikipedia API
        time.sleep(1)

if __name__ == "__main__":
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

        create_constraints(driver)

        start_pages = ["Graph database", "Neo4j", "World Wide Web"]

        populate_database(driver, start_pages, max_depth=7)

        print("\nPopulation complete!")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'driver' in locals() and driver:
            driver.close()
