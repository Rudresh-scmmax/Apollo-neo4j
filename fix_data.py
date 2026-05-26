"""
Fix two issues in Neo4j:
1. Fix material labels where rdfs__label = 'nan' - use material_description from PSQL
2. Delete old TTL BenchmarkPrice nodes (no Magnitude link) to stop price mixing
"""
import json, boto3
from neo4j import GraphDatabase

NEO4J_URI = "bolt://44.202.98.128:7687"
NEO4J_AUTH = ("neo4j", "neo4j@123")

TARGET_FUNCTION = "dev-private_db_query"
boto_client = boto3.client("lambda", region_name="us-east-1")

def database_query(query):
    payload = json.dumps({"query": query, "params": []})
    resp = boto_client.invoke(FunctionName=TARGET_FUNCTION, InvocationType="RequestResponse", Payload=payload)
    result = json.load(resp["Payload"])
    if "body" in result:
        return json.loads(result["body"])
    return result

driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

# ── FIX 1: Repair material labels that are 'nan' ────────────────────────────
print("=== FIX 1: Repairing material labels with 'nan' ===")
# Fetch all materials from PSQL
mat_rows = database_query("SELECT material_id, material_name, material_description FROM material_master")
print(f"  Fetched {len(mat_rows)} materials from PSQL")

fixed = 0
with driver.session() as s:
    for m in mat_rows:
        mat_id = m.get("material_id", "")
        # Determine proper name - skip NaN values
        name = m.get("material_name")
        if not name or str(name).lower() in ("nan", "none", "null", ""):
            name = m.get("material_description")
        if not name or str(name).lower() in ("nan", "none", "null", ""):
            name = mat_id
        name = str(name).strip()

        mat_uri = f"http://www.apollo-procurement.org/ontology#Material_{mat_id}"
        result = s.run(
            """
            MATCH (m:ns0__MaterialRequiredForProduction {uri: $uri})
            WHERE m.rdfs__label = 'nan' OR m.rdfs__label IS NULL OR m.rdfs__label = ''
            SET m.rdfs__label = $name
            RETURN count(m) as updated
            """,
            uri=mat_uri, name=name
        )
        r = result.single()
        if r and r["updated"] > 0:
            fixed += 1
            if fixed <= 5:
                print(f"  Fixed: {mat_id} -> '{name}'")

print(f"  Total labels fixed: {fixed}")

# ── FIX 2: Delete OLD TTL BenchmarkPrice nodes (no Magnitude) ───────────────
print("\n=== FIX 2: Removing old TTL BenchmarkPrice nodes (no Magnitude link) ===")
with driver.session() as s:
    # Count first
    count_r = s.run("""
        MATCH (p:ns0__BenchmarkPrice)
        WHERE NOT (p)-[:ns0__hasMagnitude]->()
        AND p.uri STARTS WITH 'benchmark_price_'
        RETURN count(p) as cnt
    """).single()
    print(f"  Old TTL BenchmarkPrice nodes to delete: {count_r['cnt']}")

    # Delete them (detach removes all relationships too)
    s.run("""
        MATCH (p:ns0__BenchmarkPrice)
        WHERE NOT (p)-[:ns0__hasMagnitude]->()
        AND p.uri STARTS WITH 'benchmark_price_'
        DETACH DELETE p
    """)
    print("  Deleted old TTL BenchmarkPrice nodes.")

# ── VERIFY ──────────────────────────────────────────────────────────────────
print("\n=== VERIFICATION ===")
with driver.session() as s:
    # Check acetic acid label
    r = s.run("""
        MATCH (m:ns0__MaterialRequiredForProduction {ns0__material_id: '102089-000000'})
        RETURN m.rdfs__label as label
    """).single()
    print(f"  Acetic Acid label: '{r['label']}'")

    # Check glycerine price nodes
    r2 = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)
        WHERE m.ns0__material_id = '100724-000000'
        OPTIONAL MATCH (p)-[:ns0__hasMagnitude]->(mag)
        RETURN count(p) as total, count(mag) as with_mag
    """).single()
    print(f"  Glycerine prices: total={r2['total']}, with_magnitude={r2['with_mag']}")

    # Check glycerine latest price
    r3 = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m),
              (p)-[:ns0__hasMagnitude]->(mag)
        WHERE m.ns0__material_id = '100724-000000'
        RETURN p.ns0__price_date as date, mag.ns1__numericValue as price, mag.ns1__unit as unit
        ORDER BY date DESC LIMIT 3
    """)
    print("  Glycerine latest prices:")
    for row in r3:
        print(f"    {row['date']} -> {row['price']} {row['unit']}")

    # Check acetic acid price
    r4 = s.run("""
        MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m),
              (p)-[:ns0__hasMagnitude]->(mag)
        WHERE m.ns0__material_id = '102089-000000'
        RETURN p.ns0__price_date as date, mag.ns1__numericValue as price, mag.ns1__unit as unit
        ORDER BY date DESC LIMIT 3
    """)
    print("  Acetic Acid latest prices:")
    for row in r4:
        print(f"    {row['date']} -> {row['price']} {row['unit']}")

driver.close()
print("\nDone.")
