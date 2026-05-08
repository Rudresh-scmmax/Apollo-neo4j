import time
from neo4j import GraphDatabase

URI = "neo4j+s://f84de943.databases.neo4j.io"
AUTH = ("neo4j", "RZnP8xQP-erwTnijGmx6k4IiIgFOjyGcQJqUDt0r46E")

print("Checking connection...")
for i in range(10):
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            driver.verify_connectivity()
            print("Connected to Neo4j!")
            break
    except Exception as e:
        print(f"Attempt {i+1} failed:", e)
        time.sleep(10)
