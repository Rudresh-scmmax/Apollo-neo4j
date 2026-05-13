import sys
import os
import json
import logging
import hashlib
import re
from neo4j import GraphDatabase

# We handle the import locally
try:
    import fitz
    from llm_module import generate_takeaways, news_agent, price_by_date_agent
except ImportError as e:
    print(f"Error importing dependencies: {e}. Please ensure PyMuPDF (fitz) and llm_module.py are present.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Remote Neo4j configuration
URI = "bolt://44.202.98.128:7687"
AUTH = ("neo4j", "neo4j@123")
REPORTS_DIR = "reports"
MATERIAL_NAME = "Glycerine"

def get_hash(text):
    return hashlib.md5(str(text).encode()).hexdigest()

def normalize_date(date_str):
    """
    Very basic normalization to YYYY-MM-DD. 
    """
    if not date_str: return "Unknown"
    date_str = date_str.strip()
    
    # Already YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
        
    # Handle DD-Mon-YYYY (e.g. 09-Nov-2023)
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
        "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
    }
    match = re.search(r"(\d{1,2})-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(\d{4})", date_str, re.I)
    if match:
        day, mon, year = match.groups()
        return f"{year}-{months[mon]}-{day.zfill(2)}"
        
    return date_str

def extract_text_from_pdf(pdf_path):
    logger.info(f"Extracting text from {pdf_path}...")
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    logger.info(f"Extracted {len(text)} characters of text.")
    return text

def ingest_to_neo4j(takeaways, news, prices, pdf_name):
    logger.info(f"Ingesting data from {pdf_name}...")
    report_url = f"file:///reports/{pdf_name}"
    
    try:
        takeaways_dict = json.loads(takeaways)
        takeaway_list = takeaways_dict.get("takeaway_list", [])
        publication = takeaways_dict.get("publication", "Unknown")
        published_date = normalize_date(takeaways_dict.get("published_date", "Unknown"))
    except Exception as e:
        logger.error(f"Failed to parse takeaways: {e}")
        takeaway_list = []
        publication = "Unknown"
        published_date = "Unknown"

    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                
                # 1. Get or Create Material URI
                material_uri = f"http://www.apollo-procurement.org/ontology#{MATERIAL_NAME.replace(' ', '_')}"
                
                # Ensure Material node exists
                session.run("""
                MERGE (m:ns0__MaterialRequiredForProduction {uri: $uri})
                SET m.rdfs__label = $material_name, m:Resource
                """, material_name=MATERIAL_NAME, uri=material_uri)
                
                # 2. Ingest Takeaways as ns0__Assertion
                for t in takeaway_list:
                    uid = f"assertion_{get_hash(t + published_date)}"
                    session.run("""
                    MATCH (m:ns0__MaterialRequiredForProduction {uri: $m_uri})
                    MERGE (a:ns0__Assertion:Resource {uri: $uri})
                    SET a.ns0__content = $content, 
                        a.ns0__publication = $publication, 
                        a.ns0__date = $date,
                        a.rdfs__label = 'Assertion'
                    MERGE (a)-[:ns0__RELATES_TO]->(m)
                    """, m_uri=material_uri, content=t, publication=publication, 
                         date=published_date, uri=uid)

                # 3. Ingest News as ns0__MarketEvent
                for n in news:
                    title = n.get("title", "")
                    date = normalize_date(n.get("published_date", ""))
                    uid = f"news_{get_hash(title + date)}"
                    session.run("""
                    MATCH (m:ns0__MaterialRequiredForProduction {uri: $m_uri})
                    MERGE (e:ns0__MarketEvent:Resource {uri: $uri})
                    SET e.ns0__title = $title, 
                        e.ns0__date = $date, 
                        e.ns0__region = $region,
                        e.ns0__url = $url,
                        e.rdfs__label = $title
                    MERGE (e)-[:ns0__IMPACTS]->(m)
                    """, m_uri=material_uri, title=title, 
                         date=date, region=n.get("region", ""), 
                         url=report_url, uri=uid)

                # 4. Ingest Prices as ns0__PriceEvent (renamed from PriceObservation)
                # Validation requirement: must have price_date and chemical_id_ref
                for p in prices:
                    price = str(p.get("price", 0.0))
                    price_date = normalize_date(p.get("date", ""))
                    uom = p.get("uom", "")
                    uid = f"price_event_{get_hash(price + price_date + uom)}"
                    
                    session.run("""
                    MATCH (m:ns0__MaterialRequiredForProduction {uri: $m_uri})
                    MERGE (pe:ns0__PriceEvent:Resource {uri: $uri})
                    SET pe.ns0__price = $price, 
                        pe.ns0__price_date = $price_date, 
                        pe.ns0__chemical_id_ref = $m_uri,
                        pe.ns0__uom = $uom, 
                        pe.ns0__region = $region, 
                        pe.ns0__price_type = $price_type,
                        pe.rdfs__label = 'Price Event ' + $price_date
                    MERGE (pe)-[:ns0__OBSERVED_FOR]->(m)
                    """, m_uri=material_uri, price=price, 
                         price_date=price_date, uom=uom, 
                         region=p.get("region", ""), price_type=p.get("price_type", ""), uri=uid)
                
    except Exception as e:
        logger.error(f"Failed to ingest data for {pdf_name}: {e}")

def process_all_pdfs():
    if not os.path.exists(REPORTS_DIR):
        logger.error(f"Reports directory not found: {REPORTS_DIR}")
        return
        
    pdf_files = [f for f in os.listdir(REPORTS_DIR) if f.lower().endswith('.pdf')]
    logger.info(f"Found {len(pdf_files)} PDF reports.")
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(REPORTS_DIR, pdf_file)
        text = extract_text_from_pdf(pdf_path)
        
        logger.info(f"Processing {pdf_file}...")
        takeaways = generate_takeaways(text, MATERIAL_NAME)
        news = news_agent(text, MATERIAL_NAME, pdf_file) 
        prices = price_by_date_agent(text, MATERIAL_NAME)
        
        ingest_to_neo4j(takeaways, news, prices, pdf_file)

if __name__ == "__main__":
    process_all_pdfs()
