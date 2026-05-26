import sys
import os
import json
import logging
import re
from neo4j import GraphDatabase
from llm_module import invoke_bedrock_text
from intent_system import IntentSystem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Remote Neo4j configuration
URI = "bolt://44.202.98.128:7687"
AUTH = ("neo4j", "neo4j@123")

def get_graph_schema(driver):
    """
    Fully dynamic schema discovery: Labels, Properties, Relationships, and Directions.
    """
    with driver.session() as session:
        # 1. Labels and their properties
        labels_res = session.run("CALL db.labels()")
        labels = [r[0] for r in labels_res]
        
        label_context = {}
        for label in labels:
            # Get distinct keys
            props_res = session.run(f"MATCH (n:{label}) UNWIND keys(n) AS k RETURN DISTINCT k LIMIT 50")
            props = [r[0] for r in props_res]
            
            # Get sample values for each property (important for semantic understanding)
            samples = {}
            for p in props:
                # Limit samples to avoid massive context
                sample_val_res = session.run(f"MATCH (n:{label}) WHERE n.{p} IS NOT NULL RETURN DISTINCT n.{p} LIMIT 3")
                samples[p] = [str(r[0]) for r in sample_val_res]
                
            label_context[label] = {"properties": props, "samples": samples}
        
        # 2. Relationship structure (StartNode)-[:REL]->(EndNode)
        structure_res = session.run("""
            MATCH (a)-[r]->(b) 
            WITH labels(a) as start_labels, type(r) as rel_type, labels(b) as end_labels
            UNWIND start_labels as start
            UNWIND end_labels as end
            RETURN DISTINCT start, rel_type, end
        """)
        structure = [f"({r['start']})-[:{r['rel_type']}]->({r['end']})" for r in structure_res]
        
        # 3. Global Date Context (Crucial for supply chain)
        date_res = session.run("""
            MATCH (n) 
            WHERE n.ns0__date IS NOT NULL 
            RETURN min(n.ns0__date) as min_date, max(n.ns0__date) as max_date
        """)
        date_info = date_res.single()
        min_date = date_info['min_date'] if date_info and date_info['min_date'] else "2023-01-01"
        max_date = date_info['max_date'] if date_info and date_info['max_date'] else "2024-12-31"
        
        return {
            "label_context": label_context,
            "structure": structure,
            "date_range": {"min": min_date, "max": max_date}
        }

def get_cypher_from_question(question, schema, intent=None):
    """
    Dynamic Cypher Generation using discovered schema context and classified intent.
    """
    intent_context = ""
    if intent:
        intent_context = f"\nCLASSIFIED INTENT:\n{json.dumps(intent, indent=2)}\n"

    system_msg = f"""
    You are a Neo4j Cypher expert. Translate the user's question into a query using the DISCOVERED SCHEMA below.
    {intent_context}
    
    SCHEMA CONTEXT (Labels & Properties):
    {json.dumps(schema['label_context'], indent=2)}
    
    VALID GRAPH PATHS:
    {schema['structure']}
    
    TEMPORAL CONTEXT:
    Earliest data: {schema['date_range']['min']}
    Latest data: {schema['date_range']['max']}
    
    STRICT RULES:
    1. Only use labels, properties, and relationships explicitly listed in the SCHEMA CONTEXT and VALID GRAPH PATHS above.
    2. DYNAMIC MATERIAL MATCH: 
       - If the user provides a numeric ID, match EXACTLY using `m.ns0__material_id = 'THE_ID'`.
       - If the user provides a text name, use regex match on BOTH label and URI: `(m.rdfs__label =~ '(?i).*THE_NAME.*' OR m.uri =~ '(?i).*THE_NAME.*')`.
       - IMPORTANT: Some material nodes (like `http://api.stardog.com/Glycerine`) ONLY have labels `Resource` and `owl__NamedIndividual` with NO `rdfs__label` property. Use `(m)` without label constraints and match using both label and URI regex.
       - Disruption events connect to `ns0__MaterialRequiredForProduction` nodes (e.g. `Glycerine Refined`) which DO have `rdfs__label`. Use label regex for disruption queries.
    3. MAGNITUDE PRICE VALUE: BenchmarkPrice and TransactionPrice do NOT have a direct price property. The actual numeric price value is in a related `ns1__Magnitude` node. 
       - You MUST join them using: `(p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)` and retrieve/filter on `mag.ns1__numericValue`.
    4. DATA DICTIONARY / RELATIONSHIPS:
       - Benchmark Pricing: `(p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)` — BenchmarkPrice points TO material (never reversed).
       - Transaction Pricing (PO prices): `(s:ns0__ProcurementSummary)-[:ns0__procuredMaterial]->(m)` and `(s)-[:ns0__hasTransactionPrice]->(t:ns0__TransactionPrice)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)`.
       - Disruptions & News Events: `(e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m)` or `(e:ns0__ForceMajeureEvent)-[:ns0__affectsMaterial]->(m)`. (Do NOT use `ns0__MarketEvent`). Dates: `(e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent)`. Use `toString(te.ns1__startDateTime) >= 'YYYY-MM-DD'` for date filtering.
       - Assertions/Takeaways: `(a:ns0__Assertion)-[:ns0__isAbout]->(m)`
       - Pricing Locations: CRITICAL — `(p:ns0__BenchmarkPrice)-[:ns0__applicableLocation]->(geo:ns1__GeoLocation)`. Node label is `ns1__GeoLocation` NOT `ns1__GeoRegion`. If location filtering returns 0 results, remove the location clause.
       - Disruption Locations: `(e)-[:ns0__hasLocation]->(loc:ns1__GeoRegion)` — disruption events use `ns1__GeoRegion`.
    5. DYNAMIC NULL FILTERING: When the user asks for 'latest', 'recent', or specific values, ALWAYS add a `WHERE` clause to filter out NULLs. 
    6. NO DOUBLE WHERE CLAUSES: Use comma-separated MATCH patterns and a single WHERE clause with AND conditions.
    7. MANDATORY OUTPUT FORMAT: You MUST return a JSON object with a single key "query". DO NOT return raw Cypher.
       Example: {{"query": "MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m) WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*') MATCH (p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude) WHERE p.ns0__price_date IS NOT NULL RETURN p.ns0__price_date as date, mag.ns1__numericValue as price ORDER BY date DESC LIMIT 1"}}
    """

    
    result = invoke_bedrock_text(system_msg, question)
    if result and isinstance(result, dict):
        cypher = result.get("query")
        if cypher:
            # Basic cleanup if LLM includes markdown
            cypher = cypher.replace("```cypher", "").replace("```", "").strip()
            return cypher
    return None

def summarize_answer(question, data):
    system_msg = """
    You are a professional supply chain analyst. Your goal is to provide a clear, professional summary based EXCLUSIVELY on the provided Graph Data.
    
    INSTRUCTIONS:
    - If 'Graph Data' contains pricing, news, or assertions, you MUST summarize them.
    - Mention specific price ranges, dates, and regions found in the data.
    - If data is present in the context, do NOT say you couldn't find matches. 
    - You MUST return your final response as a JSON object with a single key "answer".
    - Example: {"answer": "Based on market data, the latest price for Glycerine Refined is..."}
    """
    # Limit and deduplicate
    unique_data = []
    seen = set()
    for d in data:
        s = str(d)
        if s not in seen:
            unique_data.append(d)
            seen.add(s)
    
    context = f"Question: {question}\nGraph Data: {json.dumps(unique_data[:20], default=str)}"
    result = invoke_bedrock_text(system_msg, context)
    
    if isinstance(result, dict) and "answer" in result:
        return result["answer"]
    
    # Fallback formatting if LLM fails to return the exact JSON structure
    if unique_data:
        summary_points = []
        for item in unique_data[:10]:
            vals = [str(v) for v in item.values() if v]
            summary_points.append(" - " + " | ".join(vals))
        return "I found the following information:\n" + "\n".join(summary_points)
        
    return "I couldn't find enough specific data to provide a detailed summary."

def chatbot():
    print("\n" + "="*50)
    print("   APOLLO DYNAMIC SEMANTIC CHATBOT (v12.2)   ")

    print("="*50)
    print("Type 'exit' or 'quit' to stop.")
    print("Type 'refresh' to re-discover the graph schema.")
    
    driver = None
    try:
        driver = GraphDatabase.driver(URI, auth=AUTH)
        driver.verify_connectivity()
        
        print("\n[*] Discovering graph schema...")
        schema = get_graph_schema(driver)
        logger.info(f"Schema discovered: {len(schema['label_context'])} labels, {len(schema['structure'])} relationship paths.")
        
        while True:
            try:
                question = input("\nUser: ").strip()
                if not question: continue
                if question.lower() in ['exit', 'quit']: break
                
                if question.lower() == 'refresh':
                    print("[*] Refreshing schema...")
                    schema = get_graph_schema(driver)
                    print("[+] Schema updated.")
                    continue
                    
                print("[*] Classifying intent...")
                intent_system = IntentSystem()
                intent_obj = intent_system.process_question(question)
                logger.info(f"Classified Intent Object: {json.dumps(intent_obj)}")
                
                print("[*] Generating query based on intent...")
                # Pass the intent object to help with Cypher generation
                cypher = get_cypher_from_question(question, schema, intent_obj)
                
                if not cypher:
                    print("Bot: I'm sorry, I couldn't generate a valid query for that question.")
                    continue
                    
                logger.info(f"Generated Cypher: {cypher}")
                
                with driver.session() as session:
                    result = session.run(cypher)
                    raw_data = []
                    for record in result:
                        item = {}
                        for k, v in record.items():
                            if hasattr(v, 'labels'): # Node
                                item[k] = dict(v)
                            elif hasattr(v, 'type'): # Relationship
                                item[k] = dict(v)
                            else:
                                item[k] = v
                        raw_data.append(item)
                    
                    if not raw_data:
                        print("Bot: I couldn't find any matching information.")
                        continue
                        
                    # Pre-check for very large results
                    if len(raw_data) > 20:
                        logger.info(f"Large result set ({len(raw_data)} rows). Pruning for summarizer.")
                        
                    print(f"\nBot: {summarize_answer(question, raw_data)}")

                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Bot Error: {e}")
                logger.error(f"Chatbot loop error: {e}", exc_info=True)
                    
    except Exception as e:
        print(f"Bot Connection Error: {e}")
    finally:
        if driver:
            driver.close()
    print("\nBot: Goodbye!")

if __name__ == "__main__":
    chatbot()

