import import_ontology
import process_pdf_to_neo4j
import setup_vector_index
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ETL_Pipeline")

def run_pipeline():
    logger.info("Starting Apollo Market Intelligence ETL Pipeline")
    
    # Step 1: Ontology Sync
    try:
        logger.info("--- STEP 1: Synchronizing Ontology ---")
        import_ontology.import_ontology("apollo5.ttl")
    except Exception as e:
        logger.error(f"Ontology sync failed: {e}")
        # We continue as ontology might already be fine
    
    # Step 2: PDF Ingestion (Incremental)
    try:
        logger.info("--- STEP 2: Ingesting New Market Reports ---")
        process_pdf_to_neo4j.process_all_pdfs()
    except Exception as e:
        logger.error(f"PDF ingestion failed: {e}")
        raise
        
    # Step 3: Vector Sync (Incremental)
    try:
        logger.info("--- STEP 3: Synchronizing Vector Index ---")
        setup_vector_index.setup_vector_index()
    except Exception as e:
        logger.error(f"Vector sync failed: {e}")
        raise

    logger.info("Apollo ETL Pipeline completed successfully!")

if __name__ == "__main__":
    run_pipeline()
