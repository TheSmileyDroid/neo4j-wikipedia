

import os
import time
import wikipediaapi
from neo4j import GraphDatabase
from dotenv import load_dotenv
load_dotenv()

# --- Configuration ---
ONGDB_URI = os.environ.get("ONGDB_URI", "bolt://localhost:7687")
ONGDB_USER = os.environ.get("ONGDB_USER", "ongdb")
ONGDB_PASSWORD = os.environ.get("ONGDB_PASSWORD", "password")
WIKI_LANGUAGE = "pt"
WIKI_USER_AGENT = "OngDB-Wikipedia-Visualizer/1.0 (https://github.com/TheSmileyDroid)"
# --- End Configuration ---

def create_constraints(driver):
    """
    Ensures the database has the correct constraints for efficient operation.
    """
    with driver.session() as session:
        session.run("CREATE CONSTRAINT ON (p:Page) ASSERT p.title IS UNIQUE")
    print("Constraint on :Page(title) created.")

def populate_database(driver, start_pages, max_depth=2):
    """
    Crawls Wikipedia from a set of start pages and populates the OngDB database.
    """
    wiki_api = wikipediaapi.Wikipedia(WIKI_LANGUAGE, headers={"User-Agent": WIKI_USER_AGENT})

    queue = [(page, 0) for page in start_pages]
    visited = set()

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
        driver = GraphDatabase.driver(ONGDB_URI, auth=(ONGDB_USER, ONGDB_PASSWORD))

        create_constraints(driver)

        # You can change these starting pages to explore different topics
        start_pages = ["Graph database", "Neo4j", "World Wide Web"]

        populate_database(driver, start_pages, max_depth=3)

        print("\nPopulation complete!")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'driver' in locals() and driver:
            driver.close()
