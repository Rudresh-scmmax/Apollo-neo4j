import sys
import os
import json
import logging
import re
from neo4j import GraphDatabase
from llm_module import invoke_bedrock_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Local Neo4j configuration
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "Apollo@123")

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

def get_cypher_from_question(question, schema):
    """
    Dynamic Cypher Generation using discovered schema context.
    """
    system_msg = f"""
    You are a Neo4j Cypher expert. Translate the user's question into a query using the DISCOVERED SCHEMA below.
    
    SCHEMA CONTEXT (Labels & Properties):
    {json.dumps(schema['label_context'], indent=2)}
    
    VALID GRAPH PATHS:
    {schema['structure']}
    
    TEMPORAL CONTEXT:
    Earliest data: {schema['date_range']['min']}
    Latest data: {schema['date_range']['max']}
    
    RULES:
    1. Only use labels, properties, and relationships from the schema.
    2. Property names often use prefixes like 'ns0__' or 'rdfs__'. Use them exactly.
    3. Use 'rdfs__label' for human-readable matching.
    4. For 'latest', 'current', or 'recent', filter by date: {schema['date_range']['max']}.
    5. Match material names using `n.rdfs__label =~ '(?i)material_name'`.
    6. For "takeaways", "findings", or "reports", look for `ns0__Assertion` nodes.
    7. Use `DISTINCT` to avoid duplicate results.
    8. Use simple aliases (e.g., `RETURN n.ns0__content AS takeaway`). DO NOT RETURN MAPS like `{{a:b}}`.
    9. Avoid Cartesian products. If matching multiple items, use `UNION`.
    10. Return ONLY a JSON object: {{"query": "MATCH ... RETURN ..."}}
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
    You are a professional supply chain analyst. Your goal is to provide a clear, professional summary.
    
    INSTRUCTIONS:
    - Synthesize the provided graph data into a natural language response.
    - Mention specific price ranges, dates, and regions found in the data.
    - If the data contains assertions or takeaways, group them logically.
    - You MUST return your final response as a JSON object with a single key "answer".
    - Example: {"answer": "The latest price for Glycerine is..."}
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
                    
                print("[*] Processing question...")
                cypher = get_cypher_from_question(question, schema)
                
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

