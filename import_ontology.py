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
                session.run("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS FOR (r:Resource) REQUIRE r.uri IS UNIQUE").consume()
            except Exception as e:
                print(f"Constraint creation note: {e}")
                
            try:
                session.run("CALL n10s.graphconfig.init({handleVocabUris: 'SHORTEN'})").consume()
            except Exception as e:
                print(f"Graphconfig initialization note: {e}")
            
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

                # Enrich database automatically after import to prevent cardinality violations on price_date
                print("\nEnriching database automatically after import...")
                
                # Query 1: Copy dates from temporal extents
                q1 = """
                MATCH (n:ns0__BenchmarkPrice)-[:ns0__hasTemporalExtent]->(t)
                WHERE n.ns0__price_date IS NULL AND t.ns1__startDateTime IS NOT NULL
                SET n.ns0__price_date = substring(toString(t.ns1__startDateTime), 0, 10)
                RETURN count(n) as updated_cnt
                """
                res1 = session.run(q1).single()
                print(f"Updated {res1['updated_cnt']} nodes from temporal extents.")
                
                # Query 2: Set specific date for Obs_Glycerine_Crude_CIF_China_Nov13
                q2 = """
                MATCH (n:ns0__BenchmarkPrice {uri: "http://api.stardog.com/Obs_Glycerine_Crude_CIF_China_Nov13"})
                WHERE n.ns0__price_date IS NULL
                SET n.ns0__price_date = "2025-11-13"
                RETURN count(n) as updated_cnt
                """
                res2 = session.run(q2).single()
                print(f"Updated Obs_Glycerine_Crude_CIF_China_Nov13: {res2['updated_cnt']}")
                
                # Query 3: Set specific date for Obs_Acetone_US_Sept25
                q3 = """
                MATCH (n:ns0__BenchmarkPrice {uri: "http://api.stardog.com/Obs_Acetone_US_Sept25"})
                WHERE n.ns0__price_date IS NULL
                SET n.ns0__price_date = "2025-09-01"
                RETURN count(n) as updated_cnt
                """
                res3 = session.run(q3).single()
                print(f"Updated Obs_Acetone_US_Sept25: {res3['updated_cnt']}")

                # Query 4: Clean up duplicate hasTemporalExtent relationships from multiple imports
                print("\nCleaning up duplicate hasTemporalExtent relationships to enforce SHACL cardinality...")
                q4 = """
                MATCH (n:ns0__BenchmarkPrice)-[r:ns0__hasTemporalExtent]->(t)
                WITH n, collect(r) as rels
                WHERE size(rels) > 1
                UNWIND tail(rels) as rel_to_delete
                DELETE rel_to_delete
                RETURN count(rel_to_delete) as deleted_cnt
                """
                res4 = session.run(q4).single()
                print(f"Cleaned up {res4['deleted_cnt']} duplicate hasTemporalExtent relationships.")
                
            except Exception as inner_e:
                print(f"DETAILED ERROR: {inner_e}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        driver.close()

if __name__ == "__main__":
    # Prioritizing the updated apollo5.ttl as discussed
    import_ontology("apollo5.ttl")
