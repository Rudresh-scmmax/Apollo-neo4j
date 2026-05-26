"""
etl_pipeline.py
Apollo Market Intelligence ETL Pipeline

Steps:
  1. Ontology Sync  — imports apollo5.ttl into Neo4j (base ontology structure)
  2. PSQL → Neo4j   — fetches all tables from PostgreSQL and ingests into graph
  3. Vector Index   — syncs the assertion_index for semantic search
"""
import relational_to_graph_etl
import setup_vector_index
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ETL_Pipeline")


def run_pipeline(material_ids: list = None):
    """
    Run the full ETL pipeline.
    Args:
        material_ids: Optional list of material IDs to restrict ingestion.
                      If None, all materials are synced.
    """
    logger.info("Starting Apollo Market Intelligence ETL Pipeline")

    # Step 1: Ontology Sync
    try:
        logger.info("--- STEP 1: Synchronizing Ontology ---")
        from import_ontology import import_ontology
        import_ontology("apollo5.ttl")
    except Exception as e:
        logger.error(f"Ontology sync failed: {e}")
        # Non-fatal — ontology may already be loaded
        logger.warning("Continuing despite ontology sync error.")

    # Step 2: PSQL → Neo4j
    try:
        logger.info("--- STEP 2: Ingesting PostgreSQL Data into Neo4j ---")
        relational_to_graph_etl.fetch_and_ingest(material_ids=material_ids)
    except Exception as e:
        logger.error(f"PSQL → Neo4j ingestion failed: {e}")
        raise

    # Step 3: Vector Index Sync
    try:
        logger.info("--- STEP 3: Synchronizing Vector Index ---")
        setup_vector_index.setup_vector_index()
    except Exception as e:
        logger.error(f"Vector sync failed: {e}")
        raise

    logger.info("Apollo ETL Pipeline completed successfully!")


if __name__ == "__main__":
    run_pipeline()
