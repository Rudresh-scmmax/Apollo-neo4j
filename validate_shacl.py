from neo4j import GraphDatabase

URI = "bolt://44.202.98.128:7687"
AUTH = ("neo4j", "neo4j@123")

def validate_shacl(file_path, node_uri=None):
    print(f"Reading SHACL shapes from {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        shacl_data = f.read()

    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        # First, import the shapes
        print("Importing SHACL shapes into Neo4j...")
        session.run("CALL n10s.validation.shacl.import.inline($payload, 'Turtle')", payload=shacl_data)
        
        # Next, run validation
        if node_uri:
            # Check if the node exists first
            check_exists = session.run("MATCH (n) WHERE n.uri = $node_uri RETURN count(n) as cnt", node_uri=node_uri).single()
            if not check_exists or check_exists["cnt"] == 0:
                print(f"Warning: Node with URI '{node_uri}' not found in the graph.")
            
            print(f"Running SHACL validation on node <{node_uri}> and its relations...")
            query = """
            MATCH (n) WHERE n.uri = $node_uri
            OPTIONAL MATCH (n)-[r]-(m)
            WITH collect(DISTINCT n) + [x in collect(DISTINCT m) WHERE x IS NOT NULL] AS target_nodes
            CALL n10s.validation.shacl.validateSet(target_nodes)
            YIELD focusNode, nodeType, shapeId, propertyShape, offendingValue, resultPath, severity, resultMessage
            RETURN focusNode, nodeType, shapeId, propertyShape, offendingValue, resultPath, severity, resultMessage
            """
            result = session.run(query, node_uri=node_uri)
        else:
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
            print("No violations found.")
            
    driver.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run SHACL validation in Neo4j.")
    parser.add_argument("--shapes", default="shapes.ttl", help="Path to SHACL shapes file.")
    parser.add_argument("--node", help="URI of a specific node to validate.")
    args = parser.parse_args()
    
    validate_shacl(args.shapes, args.node)
