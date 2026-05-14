from neo4j import GraphDatabase
from llm_module import get_embedding
import logging

# Remote Connection Details
URI = "bolt://44.202.98.128:7687"
USER = "neo4j"
PASSWORD = "neo4j@123"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_vector_index():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    
    try:
        with driver.session() as session:
            # 1. Fetch assertions that need embeddings
            logger.info("Fetching assertions from Neo4j...")
            result = session.run("""
                MATCH (a:ns0__Assertion) 
                WHERE a.embedding IS NULL 
                RETURN a.uri as uri, a.ns0__content as content
            """)
            assertions = [record for record in result]
            logger.info(f"Found {len(assertions)} assertions to index.")

            # 2. Generate and update embeddings
            for i, record in enumerate(assertions):
                uri = record["uri"]
                content = record["content"]
                
                if not content:
                    continue
                
                logger.info(f"[{i+1}/{len(assertions)}] Embedding assertion: {uri[:40]}...")
                embedding = get_embedding(content)
                
                if embedding:
                    session.run("""
                    MATCH (a:ns0__Assertion {uri: $uri})
                    SET a.embedding = $embedding
                    """, uri=uri, embedding=embedding)
            
            # 3. Create Vector Index (Titan V2 uses 1024 dimensions by default)
            logger.info("Creating Vector Index 'assertion_index'...")
            # We use 'vector-1.0' for Neo4j 5.x
            session.run("""
            CREATE VECTOR INDEX assertion_index IF NOT EXISTS
            FOR (n:ns0__Assertion)
            ON (n.embedding)
            OPTIONS {indexConfig: {
             `vector.dimensions`: 1024,
             `vector.similarity_function`: 'cosine'
            }}
            """)
            
            logger.info("Vector Index setup complete!")

    except Exception as e:
        logger.error(f"Failed to setup vector index: {e}")
    finally:
        driver.close()

if __name__ == "__main__":
    setup_vector_index()
