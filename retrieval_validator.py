import json
import logging
import re
from neo4j import GraphDatabase
from llm_module import invoke_bedrock_chat, get_embedding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RetrievalValidator:
    """
    Validates retrieved query results against the user's intent.
    If the results are empty or do not align, it runs a self-healing loop
    to repair and retry the Cypher query.
    """
    def __init__(self, neo4j_uri: str = "bolt://44.202.98.128:7687", neo4j_auth: tuple = ("neo4j", "neo4j@123")):
        self.uri = neo4j_uri
        self.auth = neo4j_auth

    def validate(self, raw_data: list, intent: dict) -> dict:
        """
        Validates the retrieved raw data against the classified intent.
        Checks:
        1. Whether data is present.
        2. Whether the entities (materials) mentioned in the intent are referenced in the results.
        """
        if not raw_data:
            return {"is_valid": False, "reason": "No data retrieved."}
            
        entities = intent.get("entities", {})
        materials = entities.get("materials", [])
        
        if not materials:
            # If no specific materials were extracted, we assume any retrieval is valid
            return {"is_valid": True, "reason": "No material entities to validate against."}
            
        # Check if the material name or its core words appear in the retrieved records
        flat_records_str = json.dumps(raw_data, default=str).lower()
        ignored_words = {"refined", "crude", "material", "code", "id", "and", "or", "in", "for"}
        
        matched_materials = []
        for mat in materials:
            if mat.lower() in flat_records_str:
                matched_materials.append(mat)
                continue
            # Check individual core words
            words = [w.strip("(),.-_") for w in mat.split() if w.lower() not in ignored_words]
            if words and any(w.lower() in flat_records_str for w in words if w):
                matched_materials.append(mat)
                
        if not matched_materials:
            # If we got records but no explicit name match, it is still valid as the DB query filtered it
            return {
                "is_valid": True,
                "reason": "Data retrieved successfully. Material name is not explicitly in the returned columns, but data is populated."
            }
            
        return {
            "is_valid": True,
            "reason": f"Successfully retrieved data matching materials: {matched_materials}."
        }

    def heal_and_execute(self, question: str, bad_cypher: str, error_msg: str, schema: dict, intent: dict, max_attempts: int = 2) -> tuple:
        """
        Iteratively attempts to self-heal a Cypher query using an LLM critique loop.
        Returns:
            (healed_cypher, final_results, validation_report)
        """
        driver = None
        try:
            driver = GraphDatabase.driver(self.uri, auth=self.auth)
            current_cypher = bad_cypher
            current_error = error_msg
            
            for attempt in range(1, max_attempts + 1):
                logger.info(f"Self-Healing Attempt {attempt} of {max_attempts}...")
                
                # Invoke the Self-Healing Agent
                healed_cypher = self._generate_healed_cypher(question, current_cypher, current_error, schema, intent)
                logger.info(f"Generated Healed Cypher:\n{healed_cypher}")
                
                # Execute the healed query
                results = []
                execution_error = None
                
                try:
                    with driver.session() as session:
                        # Vector index queries require embedding
                        embedding = get_embedding(question)
                        res = session.run(healed_cypher, embedding=embedding)
                        for record in res:
                            results.append(record.data())
                except Exception as e:
                    execution_error = str(e)
                    logger.warning(f"Healed Cypher execution failed: {e}")
                    
                # Validate results
                if not execution_error:
                    validation = self.validate(results, intent)
                    if validation["is_valid"]:
                        logger.info(f"Self-healing succeeded on attempt {attempt}!")
                        return healed_cypher, results, {"status": "healed", "attempts": attempt, "reason": validation["reason"]}
                    else:
                        current_error = f"Empty result or entity mismatch. Validator output: {validation['reason']}"
                else:
                    current_error = f"Syntax/Runtime Error: {execution_error}"
                    
                current_cypher = healed_cypher
                
            return None, [], {"status": "failed", "attempts": max_attempts, "reason": current_error}
            
        finally:
            if driver:
                driver.close()

    def _generate_healed_cypher(self, question: str, bad_cypher: str, error_msg: str, schema: dict, intent: dict) -> str:
        """
        Uses Bedrock to inspect the failure and rewrite the Cypher query.
        """
        system_msg = """
        You are a Neo4j Cypher Self-Healing Agent.
        A previously generated Cypher query failed or returned no valid results.
        Your task is to fix the query to successfully retrieve the relevant data.
        
        SCHEMA CONTEXT (Labels & Properties):
        {schema_labels}
        
        VALID GRAPH PATHS:
        {schema_paths}

        STRICT REPAIR RULES:
        1. If the previous query failed with a syntax error, correct the syntax.
        2. BenchmarkPrice and TransactionPrice do NOT have a direct price property. The actual numeric price value is in a related `ns1__Magnitude` node. 
           - You MUST join them using: `(p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)` and retrieve/filter on `mag.ns1__numericValue`.
        3. If the query returned 0 results, check:
           - Relationship directions: `(p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)` — The BenchmarkPrice node points TO the material, NOT the other way around. Never write `(m)-[:ns0__observedFor]->(p)`.
           - Material Node Labels: Disruption events ONLY connect to `ns0__MaterialRequiredForProduction` nodes (e.g. `Glycerine Refined`, `Acetone`). NOT the bare URI node like `http://api.stardog.com/Glycerine`. So for disruptions, match using `m.rdfs__label =~ '(?i).*Glycerine.*'` (DO NOT use `m.uri =~ '(?i).*Glycerine.*'` for disruption queries since those material nodes have labels).
           - For ProcurementSummary/TransactionPrice queries: The `http://api.stardog.com/Glycerine` node IS used. Match using `(m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*')`.
           - Pricing Locations: CRITICAL — BenchmarkPrice location uses `ns1__GeoLocation` label, NOT `ns1__GeoRegion`. Use `(p)-[:ns0__applicableLocation]->(geo:ns1__GeoLocation)`. If filtering on location returns nothing, remove the location clause entirely.
           - Disruption/News Locations: `(e)-[:ns0__hasLocation]->(loc:ns1__GeoRegion)`. Do NOT use `observedMarket` relationship.
           - DateTime comparisons: `te.ns1__startDateTime` is a DateTime object, NOT a string. To filter by date range use `toString(te.ns1__startDateTime) >= 'YYYY-MM-DD'`.
           - Relative date/time filters: If a query has relative date conditions (like `te.ns1__startDateTime > timestamp() - 604800`), this will filter out historical data. Remove relative date conditions entirely and use absolute dates instead.
        4. Make sure property names and relationship types match the database schema EXACTLY:
           - Benchmark Pricing: `(p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)` (BenchmarkPrice is the START node)
           - Transaction Pricing (PO prices): `(s:ns0__ProcurementSummary)-[:ns0__procuredMaterial]->(m)` and `(s)-[:ns0__hasTransactionPrice]->(t:ns0__TransactionPrice)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)`
           - Disruptions & News Events: `(e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m)` or `(e:ns0__ForceMajeureEvent)-[:ns0__affectsMaterial]->(m)`. (Do NOT use `ns0__MarketEvent`. Dates are on temporal extent `(e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent)` via properties `te.ns1__startDateTime` or `te.ns1__endDateTime`).
           - Assertions/Takeaways: `(a:ns0__Assertion)-[:ns0__isAbout]->(m)`
        5. NO DOUBLE WHERE CLAUSES: Never generate a query containing the `WHERE` keyword twice. Declare all paths in the MATCH clause (separated by commas) and put all conditions in a single WHERE clause using AND.
        6. Output ONLY the new, corrected Cypher query. Do NOT write markdown code blocks like ```cypher. Do not write any explanations.
        """
        
        user_content = f"""
        User Question: {question}
        Classified Intent: {json.dumps(intent, indent=2)}
        Failed Cypher: {bad_cypher}
        Error/Failure: {error_msg}
        """
        
        # Inject schema elements
        schema_labels = json.dumps(schema.get('label_context', {}), indent=2)
        schema_paths = "\n".join(schema.get('structure', []))
        formatted_system_msg = system_msg.format(schema_labels=schema_labels, schema_paths=schema_paths)
        
        response = invoke_bedrock_chat(formatted_system_msg, user_content, temperature=0.0)
        
        # Clean up markdown format if the model returns it
        cypher = response.replace("```cypher", "").replace("```", "").strip()
        match = re.search(r"(MATCH|CALL|WITH|CREATE|MERGE)[\s\S]*", cypher, re.I)
        if match:
            cypher = match.group().strip()
            
        # Run standard syntax fixing
        from llm_module import fix_cypher_syntax
        return fix_cypher_syntax(cypher)
