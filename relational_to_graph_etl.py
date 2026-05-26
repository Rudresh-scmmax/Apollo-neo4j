"""
relational_to_graph_etl.py
PSQL → Neo4j ETL Pipeline

Default scope: Glycerine (100724-000000) and Acetic Acid (102089-000000).
Pass material_ids=None to fetch_and_ingest() to sync ALL materials.

Graph schema alignment:
  material_master                    → ns0__MaterialRequiredForProduction
  price_history_data                 → ns0__BenchmarkPrice
                                       -[:ns0__hasMagnitude]-> ns1__Magnitude
                                       -[:ns0__applicableLocation]-> ns1__GeoLocation
  purchase_history_transactional_data→ ns0__ProcurementSummary
                                       -[:ns0__hasTransactionPrice]-> ns0__TransactionPrice
                                       -[:ns0__hasMagnitude]-> ns1__Magnitude
  news_insights                      → ns0__SupplyDisruptionEvent
                                       -[:ns0__hasTemporalExtent]-> ns1__TemporalExtent
                                       -[:ns0__hasLocation]-> ns1__GeoRegion
  material_research_reports          → ns0__Assertion (Glycerine + Acetic Acid only)
"""

import os
import json
import boto3
import hashlib
import logging
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("psql_to_neo4j_etl")

# ── Connection Config ────────────────────────────────────────────────────────
NEO4J_URI  = "bolt://44.202.98.128:7687"
NEO4J_AUTH = ("neo4j", "neo4j@123")

TARGET_FUNCTION = os.environ.get("PRIVATE_DB_QUERY_FUNCTION", "dev-private_db_query")
boto_client = boto3.client("lambda", region_name="us-east-1")

# Research reports are always scoped to these 2 materials
REPORT_MATERIAL_IDS = ["100724-000000", "102089-000000"]  # Glycerine, Acetic Acid

# ── Helpers ──────────────────────────────────────────────────────────────────
def get_hash(text: str) -> str:
    return hashlib.md5(str(text).encode()).hexdigest()


def database_query(query: str, params=None):
    """Invoke the private-db Lambda and return parsed JSON rows."""
    payload = json.dumps({"query": query, "params": params or []})
    resp = boto_client.invoke(
        FunctionName=TARGET_FUNCTION,
        InvocationType="RequestResponse",
        Payload=payload,
    )
    result = json.load(resp["Payload"])
    if isinstance(result, dict) and "body" in result:
        body = result["body"]
        return json.loads(body) if isinstance(body, str) else body
    return result if isinstance(result, list) else []


def str_date(val) -> str:
    """Coerce date/datetime/string to ISO YYYY-MM-DD string."""
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()[:10]
    s = str(val).strip()
    return s[:10] if len(s) >= 10 else s


def _chunks(lst, n=100):
    """Yield successive n-sized chunks from a list."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ── ETL Steps ────────────────────────────────────────────────────────────────

def fetch_location_map() -> dict:
    """Return {location_id: {"name": ..., "type": ...}} from location_master."""
    logger.info("Fetching location_master...")
    rows = database_query(
        """
        SELECT lm.location_id, lm.location_name, lt.location_type_desc
        FROM location_master lm
        JOIN location_type_master lt ON lm.location_type_id = lt.location_type_id
        """
    )
    loc_map = {}
    for r in rows:
        loc_map[r["location_id"]] = {
            "name": r["location_name"],
            "type": r["location_type_desc"],
        }
    logger.info(f"  Loaded {len(loc_map)} locations.")
    return loc_map


def ingest_materials(session, mat_rows: list):
    """Upsert material_master rows → ns0__MaterialRequiredForProduction nodes."""
    logger.info(f"Ingesting {len(mat_rows)} materials...")
    for m in mat_rows:
        mat_id = m.get("material_id", "")
        # Resolve name — skip NaN/None values from PSQL
        name = m.get("material_name")
        if not name or str(name).lower() in ("nan", "none", "null", ""):
            name = m.get("material_description")
        if not name or str(name).lower() in ("nan", "none", "null", ""):
            name = mat_id
        name = str(name).strip()

        mat_uri = f"http://www.apollo-procurement.org/ontology#Material_{mat_id}"
        session.run(
            """
            MERGE (n:ns0__MaterialRequiredForProduction {uri: $uri})
            SET n.rdfs__label      = $name,
                n.ns0__material_id = $mat_id,
                n.ns0__category    = $category,
                n.ns0__cas_no      = $cas_no,
                n.ns0__status      = $status,
                n:Resource,
                n:owl__NamedIndividual
            """,
            uri=mat_uri,
            name=name,
            mat_id=mat_id,
            category=m.get("material_category", ""),
            cas_no=m.get("cas_no", ""),
            status=m.get("material_status", ""),
        )
    logger.info("  Materials ingested.")


def ingest_benchmark_prices(session, price_rows: list, loc_map: dict):
    """
    Upsert price_history_data → ns0__BenchmarkPrice + ns1__Magnitude + ns1__GeoLocation.
    Uses UNWIND batching for performance.
    """
    logger.info(f"Ingesting {len(price_rows)} benchmark prices...")

    batch = []
    for p in price_rows:
        mat_id   = p.get("material_id", "")
        price_id = p.get("material_price_type_period_id") or get_hash(
            f"{mat_id}{p.get('period_start_date')}{p.get('price')}"
        )
        loc_id   = p.get("location_id")
        loc_info = loc_map.get(loc_id, {})
        loc_name = loc_info.get("name") or p.get("country") or "Unknown"
        price_val = p.get("price")
        batch.append({
            "mat_uri":    f"http://www.apollo-procurement.org/ontology#Material_{mat_id}",
            "bp_uri":     f"http://www.apollo-procurement.org/ontology#BP_{price_id}",
            "mag_uri":    f"http://www.apollo-procurement.org/ontology#BP_{price_id}_magnitude",
            "loc_uri":    f"http://www.apollo-procurement.org/ontology#GeoLoc_{get_hash(loc_name)}",
            "date":       str_date(p.get("period_start_date")),
            "currency":   p.get("price_currency", "USD"),
            "uom":        p.get("uom") or "",
            "price_type": p.get("price_type") or "",
            "loc_name":   loc_name,
            "price_val":  float(price_val) if price_val is not None else None,
        })

    for chunk in _chunks(batch):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (m:ns0__MaterialRequiredForProduction {uri: row.mat_uri})
            MERGE (p:ns0__BenchmarkPrice:Resource {uri: row.bp_uri})
            SET p.ns0__price_date = row.date,
                p.ns0__currency   = row.currency,
                p.ns0__uom        = row.uom,
                p.ns0__price_type = row.price_type,
                p.ns0__region     = row.loc_name,
                p.rdfs__label     = 'BenchmarkPrice ' + coalesce(row.date, '')
            MERGE (p)-[:ns0__observedFor]->(m)
            MERGE (mag:ns1__Magnitude:Resource {uri: row.mag_uri})
            SET mag.ns1__numericValue = row.price_val,
                mag.ns1__unit         = row.currency
            MERGE (p)-[:ns0__hasMagnitude]->(mag)
            MERGE (geo:ns1__GeoLocation:Resource {uri: row.loc_uri})
            SET geo.rdfs__label = row.loc_name
            MERGE (p)-[:ns0__applicableLocation]->(geo)
            """,
            rows=chunk,
        )
    logger.info("  Benchmark prices ingested.")


def ingest_transaction_prices(session, purchase_rows: list):
    """
    Upsert purchase_history_transactional_data with UNWIND batching.
    ns0__ProcurementSummary -[:ns0__procuredMaterial]-> m
    ns0__ProcurementSummary -[:ns0__hasTransactionPrice]->
      ns0__TransactionPrice -[:ns0__hasMagnitude]-> ns1__Magnitude
    """
    logger.info(f"Ingesting {len(purchase_rows)} transaction records...")

    batch = []
    for pt in purchase_rows:
        mat_id    = pt.get("material_id", "")
        tx_id     = pt.get("purchase_transaction_id") or get_hash(
            f"{mat_id}{pt.get('po_number')}{pt.get('purchase_date')}"
        )
        price_val = pt.get("cost_per_uom")
        quantity  = pt.get("quantity")
        batch.append({
            "mat_uri":       f"http://www.apollo-procurement.org/ontology#Material_{mat_id}",
            "ps_uri":        f"http://www.apollo-procurement.org/ontology#PS_{tx_id}",
            "tp_uri":        f"http://www.apollo-procurement.org/ontology#TP_{tx_id}",
            "mag_uri":       f"http://www.apollo-procurement.org/ontology#TP_{tx_id}_magnitude",
            "date":          str_date(pt.get("purchase_date")),
            "price_val":     float(price_val) if price_val is not None else None,
            "quantity":      float(quantity) if quantity is not None else None,
            "currency":      pt.get("currency_of_po", "USD"),
            "uom":           pt.get("uom", ""),
            "supplier_id":   str(pt.get("supplier_id", "")),
            "po_number":     str(pt.get("po_number", "")),
            "po_status":     pt.get("po_status", ""),
            "payment_terms": pt.get("payment_terms", ""),
            "freight_terms": pt.get("freight_terms", ""),
            "buyer_name":    pt.get("buyer_name", ""),
        })

    for chunk in _chunks(batch):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (m:ns0__MaterialRequiredForProduction {uri: row.mat_uri})
            MERGE (ps:ns0__ProcurementSummary:Resource {uri: row.ps_uri})
            SET ps.ns0__po_number     = row.po_number,
                ps.ns0__purchase_date = row.date,
                ps.ns0__supplier_id   = row.supplier_id,
                ps.ns0__po_status     = row.po_status,
                ps.ns0__payment_terms = row.payment_terms,
                ps.ns0__freight_terms = row.freight_terms,
                ps.ns0__buyer_name    = row.buyer_name,
                ps.ns0__quantity      = row.quantity,
                ps.ns0__uom           = row.uom,
                ps.rdfs__label        = 'ProcurementSummary ' + coalesce(row.date, '')
            MERGE (ps)-[:ns0__procuredMaterial]->(m)
            MERGE (tp:ns0__TransactionPrice:Resource {uri: row.tp_uri})
            SET tp.ns0__price_date = row.date,
                tp.ns0__currency   = row.currency,
                tp.ns0__uom        = row.uom,
                tp.rdfs__label     = 'TransactionPrice ' + coalesce(row.date, '')
            MERGE (ps)-[:ns0__hasTransactionPrice]->(tp)
            MERGE (mag:ns1__Magnitude:Resource {uri: row.mag_uri})
            SET mag.ns1__numericValue = row.price_val,
                mag.ns1__unit         = row.currency
            MERGE (tp)-[:ns0__hasMagnitude]->(mag)
            """,
            rows=chunk,
        )
    logger.info("  Transaction prices ingested.")


def ingest_news_insights(session, news_rows: list, loc_map: dict):
    """
    Upsert news_insights with UNWIND batching.
    ns0__SupplyDisruptionEvent -[:ns0__affectsMaterial]-> m
    ns0__SupplyDisruptionEvent -[:ns0__hasTemporalExtent]-> ns1__TemporalExtent
    ns0__SupplyDisruptionEvent -[:ns0__hasLocation]-> ns1__GeoRegion
    """
    logger.info(f"Ingesting {len(news_rows)} news insights...")

    batch = []
    for n in news_rows:
        mat_id   = n.get("material_id", "")
        news_id  = n.get("id") or get_hash(f"{mat_id}{n.get('title')}{n.get('published_date')}")
        loc_id   = n.get("location_id")
        loc_info = loc_map.get(loc_id, {})
        loc_name = loc_info.get("name") or "Unknown"
        date_val = str_date(n.get("published_date"))
        batch.append({
            "mat_uri":     f"http://www.apollo-procurement.org/ontology#Material_{mat_id}",
            "evt_uri":     f"http://www.apollo-procurement.org/ontology#NewsEvt_{news_id}",
            "te_uri":      f"http://www.apollo-procurement.org/ontology#NewsEvt_{news_id}_temporal",
            "loc_uri":     f"http://www.apollo-procurement.org/ontology#GeoReg_{get_hash(loc_name)}",
            "title":       n.get("title", ""),
            "date":        date_val,
            "source":      n.get("source", ""),
            "source_link": n.get("source_link", ""),
            "news_tag":    n.get("news_tag") or "",
            "loc_name":    loc_name,
        })

    for chunk in _chunks(batch):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (m:ns0__MaterialRequiredForProduction {uri: row.mat_uri})
            MERGE (e:ns0__SupplyDisruptionEvent:Resource {uri: row.evt_uri})
            SET e.rdfs__label         = row.title,
                e.ns0__source         = row.source,
                e.ns0__source_link    = row.source_link,
                e.ns0__news_tag       = row.news_tag,
                e.ns0__published_date = row.date
            MERGE (e)-[:ns0__affectsMaterial]->(m)
            MERGE (te:ns1__TemporalExtent:Resource {uri: row.te_uri})
            SET te.ns1__startDateTime = date(row.date),
                te.ns1__endDateTime   = date(row.date)
            MERGE (e)-[:ns0__hasTemporalExtent]->(te)
            MERGE (geo:ns1__GeoRegion:Resource {uri: row.loc_uri})
            SET geo.rdfs__label = row.loc_name
            MERGE (e)-[:ns0__hasLocation]->(geo)
            """,
            rows=chunk,
        )
    logger.info("  News insights ingested.")


def ingest_research_reports(session, report_rows: list):
    """
    Upsert material_research_reports.takeaway → ns0__Assertion nodes.
    (a:ns0__Assertion)-[:ns0__isAbout]->(m:ns0__MaterialRequiredForProduction)
    """
    logger.info(f"Ingesting {len(report_rows)} research report takeaways as Assertions...")

    batch = []
    for r in report_rows:
        mat_id    = r.get("material_id", "")
        report_id = r.get("id") or get_hash(
            f"{mat_id}{r.get('published_date')}{r.get('takeaway', '')[:80]}"
        )
        takeaway  = (r.get("takeaway") or "").strip()
        if not takeaway:
            continue
        pub_date  = str_date(r.get("published_date") or r.get("date"))
        batch.append({
            "mat_uri":     f"http://www.apollo-procurement.org/ontology#Material_{mat_id}",
            "a_uri":       f"http://www.apollo-procurement.org/ontology#Assertion_{report_id}",
            "label":       r.get("publication") or "Research Report",
            "evidence":    takeaway,
            "pub_date":    pub_date,
            "publication": r.get("publication") or "",
            "report_link": r.get("report_link") or "",
        })

    for chunk in _chunks(batch):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (m:ns0__MaterialRequiredForProduction {uri: row.mat_uri})
            MERGE (a:ns0__Assertion:Resource {uri: row.a_uri})
            SET a.rdfs__label          = row.label,
                a.ns0__snippetEvidence = row.evidence,
                a.ns0__assertionMadeAt = date(row.pub_date),
                a.ns0__publication     = row.publication,
                a.ns0__report_link     = row.report_link
            MERGE (a)-[:ns0__isAbout]->(m)
            """,
            rows=chunk,
        )
    logger.info(f"  {len(batch)} assertions ingested.")


# ── Main Entry Point ─────────────────────────────────────────────────────────

def fetch_and_ingest(material_ids: list = None):
    """
    Pull all tables from PSQL and MERGE into Neo4j.
    material_ids: list of material IDs to restrict (None = ALL materials).
    """
    logger.info("=== PSQL FETCH PHASE ===")

    if material_ids:
        mat_list  = ", ".join([f"'{m}'" for m in material_ids])
        mat_where = f"WHERE material_id IN ({mat_list})"
    else:
        mat_where = ""

    logger.info("Fetching material_master...")
    mat_rows = database_query(f"SELECT * FROM material_master {mat_where}")
    logger.info(f"  {len(mat_rows)} materials fetched.")

    logger.info("Fetching price_history_data...")
    price_rows = database_query(f"SELECT * FROM price_history_data {mat_where}")
    logger.info(f"  {len(price_rows)} price records fetched.")

    logger.info("Fetching purchase_history_transactional_data...")
    purchase_rows = database_query(f"SELECT * FROM purchase_history_transactional_data {mat_where}")
    logger.info(f"  {len(purchase_rows)} purchase records fetched.")

    logger.info("Fetching news_insights...")
    news_rows = database_query(f"SELECT * FROM news_insights {mat_where}")
    logger.info(f"  {len(news_rows)} news records fetched.")

    # Research reports always scoped to Glycerine + Acetic Acid
    report_mat_list = ", ".join([f"'{m}'" for m in REPORT_MATERIAL_IDS])
    logger.info("Fetching material_research_reports (Glycerine + Acetic Acid)...")
    report_rows = database_query(
        f"SELECT * FROM material_research_reports "
        f"WHERE material_id IN ({report_mat_list}) AND takeaway IS NOT NULL AND takeaway != ''"
    )
    logger.info(f"  {len(report_rows)} report takeaways fetched.")

    loc_map = fetch_location_map()

    logger.info("=== NEO4J INGEST PHASE ===")
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        with driver.session() as session:
            ingest_materials(session, mat_rows)
            ingest_benchmark_prices(session, price_rows, loc_map)
            ingest_transaction_prices(session, purchase_rows)
            ingest_news_insights(session, news_rows, loc_map)
            ingest_research_reports(session, report_rows)
        logger.info("=== PSQL -> Neo4j ETL COMPLETE ===")
    except Exception as e:
        logger.error(f"ETL failed: {e}")
        raise
    finally:
        driver.close()


if __name__ == "__main__":
    print("=== STARTING PSQL -> NEO4J ETL PIPELINE ===")
    # Default scope: Glycerine + Acetic Acid only.
    # To sync ALL materials: fetch_and_ingest(material_ids=None)
    SCOPE = ["100724-000000", "102089-000000"]  # Glycerine, Acetic Acid
    fetch_and_ingest(material_ids=SCOPE)
    print("=== ETL PIPELINE COMPLETE ===")
