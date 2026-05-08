import rdflib
from rdflib.namespace import RDF, RDFS, OWL
from neo4j import GraphDatabase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Neo4j configuration
URI = "neo4j+ssc://f84de943.databases.neo4j.io"
AUTH = ("neo4j", "RZnP8xQP-erwTnijGmx6k4IiIgFOjyGcQJqUDt0r46E")

# TTL file path
TTL_FILE = "apollo5.ttl"

def clean_uri(uri):
    return str(uri).split('#')[-1].split('/')[-1]

def import_schema():
    logger.info("Parsing TTL file...")
    g = rdflib.Graph()
    g.parse(TTL_FILE, format="turtle")
    logger.info(f"Parsed {len(g)} triples from {TTL_FILE}")

    classes = []
    properties = []
    instances = []
    subclasses = []
    
    # 1. Extract Classes
    for s, p, o in g.triples((None, RDF.type, OWL.Class)):
        label = g.value(s, RDFS.label)
        comment = g.value(s, RDFS.comment)
        classes.append({
            "uri": str(s),
            "name": clean_uri(s),
            "label": str(label) if label else clean_uri(s),
            "comment": str(comment) if comment else ""
        })

    # 2. Extract Object Properties
    for s, p, o in g.triples((None, RDF.type, OWL.ObjectProperty)):
        label = g.value(s, RDFS.label)
        properties.append({
            "uri": str(s),
            "name": clean_uri(s),
            "label": str(label) if label else clean_uri(s)
        })

    # 3. Extract Subclass relationships
    for s, p, o in g.triples((None, RDFS.subClassOf, None)):
        if isinstance(o, rdflib.URIRef): # Ignore blank nodes for now
            subclasses.append({
                "sub": clean_uri(s),
                "super": clean_uri(o)
            })

    # 4. Extract explicit Instances (things typed as one of our classes)
    class_uris = {rdflib.URIRef(c["uri"]) for c in classes}
    for s, p, o in g.triples((None, RDF.type, None)):
        if o in class_uris:
            label = g.value(s, RDFS.label)
            instances.append({
                "uri": str(s),
                "name": clean_uri(s),
                "class_name": clean_uri(o),
                "label": str(label) if label else clean_uri(s)
            })

    # Push to Neo4j
    logger.info("Connecting to Neo4j to import schema...")
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                # Create constraints (optional, Neo4j v5 compatible)
                session.run("CREATE CONSTRAINT class_name IF NOT EXISTS FOR (c:OntologyClass) REQUIRE c.name IS UNIQUE")
                
                # Insert Classes
                logger.info(f"Inserting {len(classes)} classes...")
                session.run("""
                UNWIND $classes AS cls
                MERGE (c:OntologyClass {name: cls.name})
                SET c.uri = cls.uri, c.label = cls.label, c.comment = cls.comment
                """, classes=classes)
                
                # Insert Properties
                logger.info(f"Inserting {len(properties)} properties...")
                session.run("""
                UNWIND $props AS prop
                MERGE (p:OntologyProperty {name: prop.name})
                SET p.uri = prop.uri, p.label = prop.label
                """, props=properties)
                
                # Insert SubClassOf relationships
                logger.info(f"Inserting {len(subclasses)} subclass relationships...")
                session.run("""
                UNWIND $subclasses AS rel
                MATCH (sub:OntologyClass {name: rel.sub})
                MATCH (sup:OntologyClass {name: rel.super})
                MERGE (sub)-[:SUBCLASS_OF]->(sup)
                """, subclasses=subclasses)
                
                # Insert Instances
                logger.info(f"Inserting {len(instances)} instances...")
                for inst in instances:
                    # Create the instance with its specific class label and a generic 'OntologyInstance' label
                    query = f"""
                    MERGE (i:OntologyInstance {{name: $name}})
                    SET i:{inst['class_name']}, i.uri = $uri, i.label = $label
                    WITH i
                    MATCH (c:OntologyClass {{name: $class_name}})
                    MERGE (i)-[:INSTANCE_OF]->(c)
                    """
                    session.run(query, name=inst["name"], uri=inst["uri"], label=inst["label"], class_name=inst["class_name"])
                
                logger.info("Schema import completed successfully!")
    except Exception as e:
        logger.error(f"Failed to import schema into Neo4j: {e}")

if __name__ == "__main__":
    import_schema()
