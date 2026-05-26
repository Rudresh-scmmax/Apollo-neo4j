"""
cleanup_scope.py
Remove all BenchmarkPrice, ProcurementSummary, TransactionPrice, 
SupplyDisruptionEvent nodes NOT linked to Glycerine or Acetic Acid.
Keeps the 2 target materials' data clean and isolated.
"""
from neo4j import GraphDatabase

NEO4J_URI  = "bolt://44.202.98.128:7687"
NEO4J_AUTH = ("neo4j", "neo4j@123")

TARGET_IDS = ["100724-000000", "102089-000000"]  # Glycerine, Acetic Acid

driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

with driver.session() as s:

    # Count before
    print("=== Before cleanup ===")
    for label, rel in [
        ("ns0__BenchmarkPrice", "ns0__observedFor"),
        ("ns0__ProcurementSummary", "ns0__procuredMaterial"),
        ("ns0__SupplyDisruptionEvent", "ns0__affectsMaterial"),
    ]:
        r = s.run(f"MATCH (n:{label}) RETURN count(n) as cnt").single()
        print(f"  {label}: {r['cnt']}")

    target_uris = [
        f"http://www.apollo-procurement.org/ontology#Material_{mid}"
        for mid in TARGET_IDS
    ]

    # Delete BenchmarkPrice nodes NOT for our 2 materials (+ their Magnitude + GeoLocation)
    print("\nRemoving out-of-scope BenchmarkPrice nodes...")
    r = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)
        WHERE NOT m.uri IN $uris
        OPTIONAL MATCH (p)-[:ns0__hasMagnitude]->(mag)
        DETACH DELETE p, mag
        RETURN count(p) as deleted
    """, uris=target_uris).single()
    print(f"  Deleted {r['deleted']} BenchmarkPrice nodes (+ Magnitudes)")

    # Delete ProcurementSummary + TransactionPrice + Magnitude NOT for our 2 materials
    print("Removing out-of-scope ProcurementSummary/TransactionPrice nodes...")
    r2 = s.run("""
        MATCH (ps:ns0__ProcurementSummary)-[:ns0__procuredMaterial]->(m)
        WHERE NOT m.uri IN $uris
        OPTIONAL MATCH (ps)-[:ns0__hasTransactionPrice]->(tp)-[:ns0__hasMagnitude]->(mag)
        DETACH DELETE ps, tp, mag
        RETURN count(ps) as deleted
    """, uris=target_uris).single()
    print(f"  Deleted {r2['deleted']} ProcurementSummary nodes (+ TransactionPrice + Magnitudes)")

    # Delete SupplyDisruptionEvent NOT for our 2 materials (+ TemporalExtent)
    print("Removing out-of-scope SupplyDisruptionEvent nodes...")
    r3 = s.run("""
        MATCH (e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m)
        WHERE NOT m.uri IN $uris
        OPTIONAL MATCH (e)-[:ns0__hasTemporalExtent]->(te)
        DETACH DELETE e, te
        RETURN count(e) as deleted
    """, uris=target_uris).single()
    print(f"  Deleted {r3['deleted']} SupplyDisruptionEvent nodes (+ TemporalExtent)")

    # Also remove old TTL BenchmarkPrice nodes (no Magnitude, old URI format)
    print("Removing leftover old-TTL BenchmarkPrice nodes (no Magnitude)...")
    s.run("""
        MATCH (p:ns0__BenchmarkPrice)
        WHERE NOT (p)-[:ns0__hasMagnitude]->()
        AND p.uri STARTS WITH 'benchmark_price_'
        DETACH DELETE p
    """)
    print("  Done.")

    # Count after
    print("\n=== After cleanup ===")
    for label in ["ns0__BenchmarkPrice", "ns0__ProcurementSummary", "ns0__SupplyDisruptionEvent"]:
        r = s.run(f"MATCH (n:{label}) RETURN count(n) as cnt").single()
        print(f"  {label}: {r['cnt']}")

    # Verify labels for our 2 materials
    print("\n=== Material labels ===")
    for mid in TARGET_IDS:
        r = s.run("""
            MATCH (m:ns0__MaterialRequiredForProduction {ns0__material_id: $mid})
            RETURN m.rdfs__label as label
        """, mid=mid).single()
        print(f"  {mid}: '{r['label'] if r else 'NOT FOUND'}'")

driver.close()
print("\nCleanup complete.")
