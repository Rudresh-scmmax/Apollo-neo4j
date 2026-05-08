from neo4j import GraphDatabase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Local Neo4j configuration
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "Apollo@123")

# TTL file path
TTL_FILE = "apollo5.ttl"

def import_schema():
    logger.info(f"Reading {TTL_FILE}...")
    try:
        with open(TTL_FILE, 'r', encoding='utf-8') as f:
            ttl_content = f.read()
    except Exception as e:
        logger.error(f"Failed to read TTL file: {e}")
        return

    logger.info("Connecting to local Neo4j to import schema using n10s...")
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                # 1. Ensure GraphConfig is initialized
                try:
                    session.run("CALL n10s.graphconfig.init({ handleVocabUris: 'SHORTEN' })")
                    logger.info("GraphConfig initialized.")
                except Exception as e:
                    logger.info("GraphConfig already exists, continuing...")

                # 2. Create the mandatory constraint for n10s
                try:
                    session.run("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS FOR (r:Resource) REQUIRE r.uri IS UNIQUE")
                    logger.info("n10s unique URI constraint ensured.")
                except Exception as e:
                    logger.info(f"Constraint might already exist: {e}")

                # 3. Import the Turtle data
                logger.info("Importing TTL data via n10s...")
                result = session.run(
                    "CALL n10s.rdf.import.inline($payload, 'Turtle')", 
                    payload=ttl_content
                )
                summary = result.single()
                logger.info(f"Import Summary: {summary}")
                
                logger.info("Schema import completed successfully!")
    except Exception as e:
        logger.error(f"Failed to import schema: {e}")

if __name__ == "__main__":
    import_schema()
