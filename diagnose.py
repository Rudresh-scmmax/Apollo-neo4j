"""Diagnose the price and acetic acid issues in Neo4j"""
from neo4j import GraphDatabase

driver = GraphDatabase.driver('bolt://44.202.98.128:7687', auth=('neo4j', 'neo4j@123'))
with driver.session() as s:

    # 1. Check acetic acid material node label
    print("=== Acetic Acid material node ===")
    r = s.run("""
        MATCH (m:ns0__MaterialRequiredForProduction)
        WHERE m.ns0__material_id = '102089-000000'
        RETURN m.uri, m.rdfs__label, m.ns0__material_id, m.ns0__category
    """)
    for row in r:
        print(f"  uri={row['m.uri']}")
        print(f"  rdfs__label={row['m.rdfs__label']}")
        print(f"  material_id={row['m.ns0__material_id']}")

    # 2. Check acetic acid price records
    print("\n=== Acetic Acid BenchmarkPrice nodes ===")
    r2 = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)
        WHERE m.ns0__material_id = '102089-000000'
        OPTIONAL MATCH (p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)
        RETURN count(p) as total, count(mag) as with_magnitude
    """)
    for row in r2:
        print(f"  Total BenchmarkPrice nodes: {row['total']}")
        print(f"  With Magnitude node: {row['with_magnitude']}")

    # 3. Check glycerine - how many prices have Magnitude vs direct property
    print("\n=== Glycerine Price Nodes breakdown ===")
    r3 = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)
        WHERE m.ns0__material_id = '100724-000000'
        OPTIONAL MATCH (p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)
        RETURN
          count(p) as total_prices,
          count(mag) as with_magnitude,
          count(p) - count(mag) as without_magnitude_old_ttl
    """)
    for row in r3:
        print(f"  Total price nodes: {row['total_prices']}")
        print(f"  With Magnitude (PSQL ETL): {row['with_magnitude']}")
        print(f"  Without Magnitude (old TTL): {row['without_magnitude_old_ttl']}")

    # 4. Sample old-style price nodes (no magnitude)
    print("\n=== Sample OLD TTL price nodes (no Magnitude) ===")
    r4 = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)
        WHERE m.ns0__material_id = '100724-000000'
        AND NOT (p)-[:ns0__hasMagnitude]->()
        RETURN p.ns0__price_date as date, p.ns0__price as price, p.uri as uri
        ORDER BY date DESC LIMIT 5
    """)
    for row in r4:
        print(f"  {row['date']} -> price={row['price']} uri={row['uri']}")

    # 5. Sample PSQL ETL price nodes (with magnitude)
    print("\n=== Sample NEW PSQL price nodes (via Magnitude) ===")
    r5 = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m),
              (p)-[:ns0__hasMagnitude]->(mag)
        WHERE m.ns0__material_id = '100724-000000'
        RETURN p.ns0__price_date as date, mag.ns1__numericValue as price, mag.ns1__unit as unit
        ORDER BY date DESC LIMIT 5
    """)
    for row in r5:
        print(f"  {row['date']} -> price={row['price']} {row['unit']}")

driver.close()
print("\nDone.")
