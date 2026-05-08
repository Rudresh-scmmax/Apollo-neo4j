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

# Local Neo4j configuration
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "Apollo@123")
PDF_FILE = "ICIS Glycerine Asia-Pacific - Pricing & Insight-09-Nov-2023.pdf"
MATERIAL_NAME = "Glycerine"
REPORT_URL = f"file:///{PDF_FILE}"

def get_hash(text):
    return hashlib.md5(str(text).encode()).hexdigest()

def normalize_date(date_str):
    """
    Very basic normalization to YYYY-MM-DD. 
    If it's already YYYY-MM-DD, return it.
    If it's DD-Mon-YYYY, convert it.
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

def ingest_to_neo4j(takeaways, news, prices):
    logger.info("Connecting to local Neo4j to ingest semantic data...")
    
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
                
                # 1. Create the Material Node
                logger.info(f"Ensuring Material node '{MATERIAL_NAME}' exists...")
                session.run("""
                MERGE (m:ns0__MaterialRequiredForProduction {rdfs__label: $material_name})
                SET m:Resource, m.ns0__name = $material_name
                """, material_name=MATERIAL_NAME)
                
                # 2. Ingest Takeaways as ns0__Assertion
                logger.info(f"Ingesting {len(takeaway_list)} takeaways...")
                for t in takeaway_list:
                    uid = f"assertion_{get_hash(t + published_date)}"
                    session.run("""
                    MATCH (m:ns0__MaterialRequiredForProduction {rdfs__label: $material_name})
                    MERGE (a:ns0__Assertion:Resource {uri: $uri})
                    SET a.ns0__content = $content, 
                        a.ns0__publication = $publication, 
                        a.ns0__date = $date,
                        a.rdfs__label = 'Assertion'
                    MERGE (a)-[:ns0__RELATES_TO]->(m)
                    """, material_name=MATERIAL_NAME, content=t, publication=publication, 
                         date=published_date, uri=uid)

                # 3. Ingest News as ns0__MarketEvent
                logger.info(f"Ingesting {len(news)} news events...")
                for n in news:
                    title = n.get("title", "")
                    date = normalize_date(n.get("published_date", ""))
                    uid = f"news_{get_hash(title + date)}"
                    session.run("""
                    MATCH (m:ns0__MaterialRequiredForProduction {rdfs__label: $material_name})
                    MERGE (e:ns0__MarketEvent:Resource {uri: $uri})
                    SET e.ns0__title = $title, 
                        e.ns0__date = $date, 
                        e.ns0__region = $region,
                        e.ns0__url = $url,
                        e.rdfs__label = $title
                    MERGE (e)-[:ns0__IMPACTS]->(m)
                    """, material_name=MATERIAL_NAME, title=title, 
                         date=date, region=n.get("region", ""), 
                         url=n.get("news_url", ""), uri=uid)

                # 4. Ingest Prices as ns0__PriceObservation
                logger.info(f"Ingesting {len(prices)} price observations...")
                for p in prices:
                    price = str(p.get("price", 0.0))
                    date = normalize_date(p.get("date", ""))
                    uom = p.get("uom", "")
                    uid = f"price_{get_hash(price + date + uom)}"
                    session.run("""
                    MATCH (m:ns0__MaterialRequiredForProduction {rdfs__label: $material_name})
                    MERGE (obs:ns0__PriceObservation:Resource {uri: $uri})
                    SET obs.ns0__price = $price, 
                        obs.ns0__date = $date, 
                        obs.ns0__uom = $uom, 
                        obs.ns0__region = $region, 
                        obs.ns0__price_type = $price_type,
                        obs.rdfs__label = 'Price Obs ' + $date
                    MERGE (obs)-[:ns0__OBSERVED_FOR]->(m)
                    """, material_name=MATERIAL_NAME, price=price, 
                         date=date, uom=uom, 
                         region=p.get("region", ""), price_type=p.get("price_type", ""), uri=uid)
                
                logger.info("Semantic data ingestion completed successfully with normalized dates!")
    except Exception as e:
        logger.error(f"Failed to ingest data to Neo4j: {e}")

def main():
    if not os.path.exists(PDF_FILE):
        logger.error(f"PDF file not found: {PDF_FILE}")
        return
        
    text = extract_text_from_pdf(PDF_FILE)
    
    logger.info("Calling AWS Bedrock for Takeaways...")
    takeaways = generate_takeaways(text, MATERIAL_NAME)
    
    logger.info("Calling AWS Bedrock for News...")
    news = news_agent(text, MATERIAL_NAME, REPORT_URL)
    logger.info(f"Extracted {len(news)} news events.")
    
    logger.info("Calling AWS Bedrock for Prices...")
    prices = price_by_date_agent(text, MATERIAL_NAME)
    logger.info(f"Extracted {len(prices)} price observations.")
    
    ingest_to_neo4j(takeaways, news, prices)

if __name__ == "__main__":
    main()
