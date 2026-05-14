from neo4j import GraphDatabase

URI = "bolt://44.202.98.128:7687"
AUTH = ("neo4j", "neo4j@123")

def check_data():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        print("--- Checking Relationships for April 24, 2025 data ---")
        res = session.run("""
            MATCH (pe:ns0__PriceEvent)
            WHERE pe.ns0__price_date CONTAINS '2025-04-24'
            OPTIONAL MATCH (pe)-[:ns0__OBSERVED_FOR]->(m)
            RETURN pe.ns0__price as price, 
                   m.rdfs__label as material_label,
                   labels(m) as material_labels
        """)
        for record in res:
            print(f"Price: {record['price']} -> Material: {record['material_label']} (Labels: {record['material_labels']})")

    driver.close()

if __name__ == "__main__":
    check_data()
