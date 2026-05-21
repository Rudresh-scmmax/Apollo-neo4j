import os
import json
import boto3
import hashlib
from datetime import datetime
from neo4j import GraphDatabase
from import_ontology import import_ontology

# Neo4j Details
NEO4J_URI = "bolt://44.202.98.128:7687"
NEO4J_AUTH = ("neo4j", "neo4j@123")

# AWS Lambda Details
TARGET_FUNCTION = os.environ.get("PRIVATE_DB_QUERY_FUNCTION", "dev-private_db_query")
boto_client = boto3.client("lambda", region_name="us-east-1")

def get_hash(text):
    return hashlib.md5(str(text).encode()).hexdigest()

def database_query(query, params=None):
    payload = json.dumps({"query": query, "params": params or []})
    resp = boto_client.invoke(
        FunctionName=TARGET_FUNCTION,
        InvocationType="RequestResponse",
        Payload=payload
    )
    result = json.load(resp["Payload"])
    if "body" in result:
        return json.loads(result["body"])
    return result

def wipe_graph():
    print("Wiping existing graph data...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    driver.close()
    print("Graph wiped successfully.")

def fetch_and_ingest():
    materials = ["100724-000000", "102089-000000"]
    mat_list = ", ".join([f"'{m}'" for m in materials])
    
    print("Fetching Material Master...")
    mat_data = database_query(f"SELECT * FROM material_master WHERE material_id IN ({mat_list})")
    
    print("Fetching Price History...")
    price_data = database_query(f"SELECT * FROM price_history_data WHERE material_id IN ({mat_list})")
    
    print("Fetching News Insights...")
    news_data = database_query(f"SELECT * FROM news_insights WHERE material_id IN ({mat_list})")
    
    print("Fetching Purchase History Transactional Data...")
    purchase_data = database_query(f"SELECT * FROM purchase_history_transactional_data WHERE material_id IN ({mat_list})")
    
    print("Connecting to Neo4j for ingestion...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    
    with driver.session() as session:
        # 1. Ingest Materials
        for m in mat_data:
            mat_id = m.get('material_id')
            mat_name = m.get('material_description') or m.get('material_name') or mat_id
            mat_uri = f"http://www.apollo-procurement.org/ontology#Material_{mat_id}"
            
            session.run("""
            MERGE (n:ns0__MaterialRequiredForProduction {uri: $uri})
            SET n.rdfs__label = $name, n.ns0__material_id = $mat_id, n:Resource
            """, uri=mat_uri, name=mat_name, mat_id=mat_id)
        
        # 2. Ingest Benchmark Prices
        for p in price_data:
            mat_id = p.get('material_id')
            mat_uri = f"http://www.apollo-procurement.org/ontology#Material_{mat_id}"
            
            price_val = str(p.get('price', ''))
            date_val = str(p.get('period_start_date', ''))
            region_val = p.get('country', '')
            uom_val = p.get('uom', '')
            currency_val = p.get('price_currency', '')
            price_type_val = p.get('price_type', '')
            
            uid = f"benchmark_price_{get_hash(f'{mat_id}{date_val}{price_val}')}"
            
            session.run("""
            MATCH (m:ns0__MaterialRequiredForProduction {uri: $mat_uri})
            MERGE (pe:ns0__BenchmarkPrice:Resource {uri: $uri})
            SET pe.ns0__price = $price,
                pe.ns0__price_date = $date,
                pe.ns0__region = $region,
                pe.ns0__uom = $uom,
                pe.ns0__currency = $currency,
                pe.ns0__price_type = $price_type,
                pe.rdfs__label = 'Benchmark Price ' + $date
            MERGE (pe)-[:ns0__observedFor]->(m)
            """, mat_uri=mat_uri, uri=uid, price=price_val, date=date_val, 
                 region=region_val, uom=uom_val, currency=currency_val, price_type=price_type_val)
            
        # 3. Ingest Transaction Prices
        for pt in purchase_data:
            mat_id = pt.get('material_id')
            mat_uri = f"http://www.apollo-procurement.org/ontology#Material_{mat_id}"
            
            price_val = str(pt.get('cost_per_uom', ''))
            date_val = str(pt.get('purchase_date', ''))
            uom_val = pt.get('uom', '')
            currency_val = pt.get('currency_of_po', '')
            supplier = str(pt.get('supplier_id', ''))
            po_num = str(pt.get('po_number', ''))
            
            uid = f"transaction_price_{get_hash(f'{mat_id}{date_val}{po_num}')}"
            
            session.run("""
            MATCH (m:ns0__MaterialRequiredForProduction {uri: $mat_uri})
            MERGE (tp:ns0__TransactionPrice:Resource {uri: $uri})
            SET tp.ns0__price = $price,
                tp.ns0__price_date = $date,
                tp.ns0__uom = $uom,
                tp.ns0__currency = $currency,
                tp.ns0__supplier_id = $supplier,
                tp.ns0__po_number = $po_num,
                tp.rdfs__label = 'Transaction Price ' + $date
            MERGE (tp)-[:ns0__observedFor]->(m)
            """, mat_uri=mat_uri, uri=uid, price=price_val, date=date_val,
                 uom=uom_val, currency=currency_val, supplier=supplier, po_num=po_num)
            
        # 4. Ingest News Insights
        for n in news_data:
            mat_id = n.get('material_id')
            mat_uri = f"http://www.apollo-procurement.org/ontology#Material_{mat_id}"
            
            title = n.get('title', '')
            date_val = str(n.get('published_date', ''))
            source = n.get('source', '')
            link = n.get('source_link', '')
            
            uid = f"market_event_{get_hash(f'{mat_id}{date_val}{title}')}"
            
            session.run("""
            MATCH (m:ns0__MaterialRequiredForProduction {uri: $mat_uri})
            MERGE (me:ns0__MarketEvent:Resource {uri: $uri})
            SET me.ns0__title = $title,
                me.ns0__date = $date,
                me.ns0__source = $source,
                me.ns0__url = $link,
                me.rdfs__label = $title
            MERGE (me)-[:ns0__affectsMaterial]->(m)
            """, mat_uri=mat_uri, uri=uid, title=title, date=date_val, source=source, link=link)

    driver.close()
    print("Data ingested successfully.")

if __name__ == "__main__":
    print("=== STARTING ETL PIPELINE ===")
    wipe_graph()
    import_ontology("apollo5.ttl")
    fetch_and_ingest()
    print("=== ETL PIPELINE COMPLETE ===")
