from neo4j import GraphDatabase
import os

# Remote Connection Details
URI = "bolt://44.202.98.128:7687"
USER = "neo4j"
PASSWORD = "neo4j@123"

def import_ontology(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    print(f"Reading {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        ttl_data = f.read()

    print(f"Connecting to remote Neo4j at {URI}...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    
    try:
        with driver.session() as session:
            # 1. Ensure graph configuration is initialized and constraint exists
            print("Checking/Initializing graph config and constraints...")
            try:
                session.run("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS FOR (r:Resource) REQUIRE r.uri IS UNIQUE")
            except Exception as e:
                print(f"Constraint creation note: {e}")
                
            session.run("CALL n10s.graphconfig.init({handleVocabUris: 'SHORTEN'})")
            
            # 2. Preview the RDF data to see errors
            print(f"Previewing ontology content ({len(ttl_data)} characters)...")
            try:
                # We use rdf.preview.inline to see what would happen and catch errors
                query = "CALL n10s.rdf.preview.inline($payload, 'Turtle')"
                result = session.run(query, payload=ttl_data)
                # If preview works, it returns a list of nodes/rels. 
                # If it fails, it usually raises an exception here.
                first_row = result.peek()
                print(f"Preview successful! Found sample data: {first_row}")
                
                # If preview works, proceed to import
                print("Proceeding to actual import...")
                query_import = "CALL n10s.rdf.import.inline($payload, 'Turtle')"
                import_res = session.run(query_import, payload=ttl_data).single()
                print("\nIMPORT DETAILED RESULT:")
                for key in import_res.keys():
                    print(f"{key}: {import_res[key]}")
            except Exception as inner_e:
                print(f"DETAILED ERROR: {inner_e}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        driver.close()

if __name__ == "__main__":
    # Prioritizing the updated apollo5.ttl as discussed
    import_ontology("apollo5.ttl")
