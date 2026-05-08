import sys
import os
import json
import logging
from neo4j import GraphDatabase

# Add path to the llm module
sys.path.append(r"c:\SCM-MAX-V2\Apollo-Lambda\Pdf_Processor")

# We handle the import in a try-except to avoid failure if fitz is not installed yet
try:
    import fitz
    from llm_module import generate_takeaways, news_agent, price_by_date_agent
except ImportError as e:
    print(f"Error importing dependencies: {e}. Please ensure PyMuPDF (fitz) is installed.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URI = "neo4j+ssc://f84de943.databases.neo4j.io"
AUTH = ("neo4j", "RZnP8xQP-erwTnijGmx6k4IiIgFOjyGcQJqUDt0r46E")
PDF_FILE = "ICIS Glycerine Asia-Pacific - Pricing & Insight-09-Nov-2023.pdf"
MATERIAL_NAME = "Glycerine"
REPORT_URL = f"file:///{PDF_FILE}"

def extract_text_from_pdf(pdf_path):
    logger.info(f"Extracting text from {pdf_path}...")
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    logger.info(f"Extracted {len(text)} characters of text.")
    return text

def ingest_to_neo4j(takeaways, news, prices):
    logger.info("Connecting to Neo4j to ingest semantic data...")
    
    # Parse takeaways (JSON string)
    try:
        takeaways_dict = json.loads(takeaways)
        takeaway_list = takeaways_dict.get("takeaway_list", [])
        publication = takeaways_dict.get("publication", "Unknown")
        published_date = takeaways_dict.get("published_date", "Unknown")
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
                MERGE (m:MaterialRequiredForProduction {name: $material_name})
                SET m:OntologyInstance, m.label = $material_name
                """, material_name=MATERIAL_NAME)
                
                # 2. Ingest Takeaways as Assertions
                logger.info(f"Ingesting {len(takeaway_list)} takeaways...")
                for t in takeaway_list:
                    session.run("""
                    MATCH (m:MaterialRequiredForProduction {name: $material_name})
                    CREATE (a:Assertion:OntologyInstance {
                        content: $content, 
                        publication: $publication, 
                        date: $date
                    })
                    CREATE (a)-[:RELATES_TO]->(m)
                    """, material_name=MATERIAL_NAME, content=t, publication=publication, date=published_date)

                # 3. Ingest News as MarketEvents
                logger.info(f"Ingesting {len(news)} news events...")
                for n in news:
                    session.run("""
                    MATCH (m:MaterialRequiredForProduction {name: $material_name})
                    CREATE (e:MarketEvent:OntologyInstance {
                        title: $title, 
                        date: $date, 
                        region: $region,
                        url: $url
                    })
                    CREATE (e)-[:IMPACTS]->(m)
                    """, material_name=MATERIAL_NAME, title=n.get("title", ""), 
                         date=n.get("published_date", ""), region=n.get("region", ""), 
                         url=n.get("news_url", ""))

                # 4. Ingest Prices as PriceObservations
                logger.info(f"Ingesting {len(prices)} price observations...")
                for p in prices:
                    session.run("""
                    MATCH (m:MaterialRequiredForProduction {name: $material_name})
                    CREATE (obs:PriceObservation:OntologyInstance {
                        price: $price, 
                        date: $date, 
                        uom: $uom, 
                        region: $region, 
                        price_type: $price_type
                    })
                    CREATE (obs)-[:OBSERVED_FOR]->(m)
                    """, material_name=MATERIAL_NAME, price=p.get("price", 0.0), 
                         date=p.get("date", ""), uom=p.get("uom", ""), 
                         region=p.get("region", ""), price_type=p.get("price_type", ""))
                
                logger.info("Data ingestion completed successfully!")
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
    
    logger.info("Calling AWS Bedrock for Prices...")
    prices = price_by_date_agent(text, MATERIAL_NAME)
    
    logger.info("Summary of extraction:")
    logger.info(f"- Takeaways: {takeaways}")
    logger.info(f"- News count: {len(news)}")
    logger.info(f"- Price count: {len(prices)}")
    
    ingest_to_neo4j(takeaways, news, prices)

if __name__ == "__main__":
    main()
