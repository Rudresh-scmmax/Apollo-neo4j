import import_ontology
import setup_vector_index
from neo4j import GraphDatabase
import os

# New Production Server IP
NEW_IP = "44.202.98.128"
NEW_URI = f"bolt://{NEW_IP}:7687"

def master_setup():
    print(f"--- STARTING MASTER SETUP FOR {NEW_IP} ---")
    
    # 0. Password Reset (Must be on system database)
    print("\n[0/4] Resetting Neo4j Password...")
    try:
        # Try connecting with neo4j/neo4j
        driver = GraphDatabase.driver(NEW_URI, auth=("neo4j", "neo4j"))
        with driver.session(database="system") as session:
            session.run('ALTER CURRENT USER SET PASSWORD FROM "neo4j" TO "neo4j@123"')
        driver.close()
        print("Password reset successful.")
    except Exception as e:
        print(f"Password reset skipped: {e}")
    
    # 1. Run Unified ETL Pipeline
    import etl_pipeline
    etl_pipeline.run_pipeline()
    
    # 2. Update App Config
    print("\n[4/4] Updating App Configuration...")
    with open("app.py", "r") as f:
        content = f.read()
    
    # Replace old IP with new IP (handles multiple occurrences)
    new_content = content.replace("18.212.194.59", NEW_IP)
    with open("app.py", "w") as f:
        f.write(new_content)
        
    print("\n" + "="*50)
    print("MASTER SETUP COMPLETE!")
    print(f"Your Production Chatbot is ready: http://{NEW_IP}:8000")
    print("="*50)

if __name__ == "__main__":
    master_setup()
