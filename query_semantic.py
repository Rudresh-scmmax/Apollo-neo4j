from neo4j import GraphDatabase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Local Neo4j configuration
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "Apollo@123")

def semantic_query():
    logger.info("Executing semantic query on local Neo4j...")
    query = """
    // 1. Find all classes in the ontology
    MATCH (c:owl__Class)
    RETURN c.rdfs__label AS classLabel, c.uri AS uri
    LIMIT 10
    """
    
    query2 = """
    // 2. Find instances and their semantic types
    MATCH (i:Resource)
    WHERE NOT i:owl__Class AND NOT i:owl__ObjectProperty AND NOT i:owl__DatatypeProperty
    RETURN labels(i) AS labels, i.rdfs__label AS label, i.ns0__title AS title, i.ns0__content AS content
    LIMIT 10
    """

    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                logger.info("--- Ontology Classes ---")
                result = session.run(query)
                for record in result:
                    print(f"Class: {record['classLabel']} ({record['uri']})")
                
                logger.info("--- Semantic Instances ---")
                result = session.run(query2)
                for record in result:
                    name = record['label'] or record['title'] or record['content'] or "Unknown"
                    print(f"Instance: {name} | Labels: {record['labels']}")
                    
    except Exception as e:
        logger.error(f"Query failed: {e}")

if __name__ == "__main__":
    semantic_query()
