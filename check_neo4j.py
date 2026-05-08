from neo4j import GraphDatabase

URI = "neo4j+ssc://f84de943.databases.neo4j.io"
AUTH = ("neo4j", "RZnP8xQP-erwTnijGmx6k4IiIgFOjyGcQJqUDt0r46E")

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    try:
        driver.verify_connectivity()
        print("Connected to Neo4j!")
        
        # Check if n10s is installed
        with driver.session() as session:
            result = session.run("SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'n10s' RETURN name")
            procedures = [record["name"] for record in result]
            if procedures:
                print("Neosemantics is installed! Procedures found:", len(procedures))
            else:
                print("Neosemantics is NOT installed.")
    except Exception as e:
        print("Failed to connect:", e)
