from neo4j import GraphDatabase

URI = "bolt://44.202.98.128:7687"
AUTH = ("neo4j", "neo4j@123")

def test_query():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        query = """
        MATCH (m:ns0__MaterialRequiredForProduction)
        WHERE m.rdfs__label CONTAINS 'Glycerine Refined'
        MATCH (pe:ns0__PriceEvent)-[:ns0__OBSERVED_FOR]->(m)
        WHERE pe.ns0__price_date CONTAINS '2025-04-24'
        RETURN pe.ns0__price, pe.ns0__uom, m.rdfs__label
        """
        print(f"Testing Query:\n{query}")
        res = session.run(query)
        found = False
        for record in res:
            found = True
            print(f"Result: {record.data()}")
        if not found:
            print("NO RESULTS FOUND")
    driver.close()

if __name__ == "__main__":
    test_query()
