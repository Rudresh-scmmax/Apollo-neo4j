import time
from neo4j import GraphDatabase

URI = "bolt+s://f84de943.databases.neo4j.io"
AUTH = ("neo4j", "RZnP8xQP-erwTnijGmx6k4IiIgFOjyGcQJqUDt0r46E")

print("Checking connection with bolt+s...")
try:
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        print("Connected to Neo4j using bolt+s!")
except Exception as e:
    print(f"Failed:", e)
