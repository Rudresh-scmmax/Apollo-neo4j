from neo4j import GraphDatabase

URI = "bolt://44.202.98.128:7687"
AUTH = ("neo4j", "neo4j@123")

def validate_shacl(file_path):
    print(f"Reading SHACL shapes from {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        shacl_data = f.read()

    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        # First, import the shapes
        print("Importing SHACL shapes into Neo4j...")
        session.run("CALL n10s.validation.shacl.import.inline($payload, 'Turtle')", payload=shacl_data)
        
        # Next, run validation
        print("Running SHACL validation on the graph...")
        result = session.run("CALL n10s.validation.shacl.validate()")
        
        violations = []
        for record in result:
            violations.append(record.data())
            
        if violations:
            print(f"Found {len(violations)} SHACL violations!")
            for v in violations[:10]:
                print(f"Node: {v.get('focusNode')}")
                print(f"Shape: {v.get('shapeId')}")
                print(f"Property Path: {v.get('resultPath')}")
                print(f"Message: {v.get('resultMessage')}")
                print(f"Offending Value: {v.get('offendingValue')}")
                print("-" * 30)
        else:
            print("Graph passes SHACL validation! No violations found.")
            
    driver.close()

if __name__ == "__main__":
    validate_shacl("shapes.ttl")
