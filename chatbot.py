import sys
import os
import json
import logging
from neo4j import GraphDatabase
from llm_module import invoke_bedrock_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Local Neo4j configuration
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "Apollo@123")

def get_graph_schema(driver):
    """
    v11 Enterprise Schema: Discovers structure, properties, and samples for fully dynamic querying.
    """
    with driver.session() as session:
        labels = [r[0] for r in session.run("CALL db.labels()")]
        
        label_context = {}
        for label in labels:
            props = [r[0] for r in session.run(f"MATCH (n:{label}) UNWIND keys(n) AS k RETURN DISTINCT k LIMIT 20")]
            sample_res = session.run(f"MATCH (n:{label}) RETURN n.rdfs__label as l, n.ns0__content as c, n.ns0__title as t LIMIT 3")
            samples = [v for r in sample_res for v in [r['l'], r['c'], r['t']] if v]
            label_context[label] = {"properties": props, "samples": samples}
        
        structure_res = session.run("""
            MATCH (a)-[r]->(b) 
            WITH labels(a)[0] as start, type(r) as rel, labels(b)[0] as end
            RETURN DISTINCT start, rel, end
        """)
        structure = [f"({r['start']})-[:{r['rel']}]->({r['end']})" for r in structure_res]
        
        date_res = session.run("MATCH (n:Resource) WHERE n.ns0__date IS NOT NULL RETURN min(n.ns0__date), max(n.ns0__date)")
        date_info = date_res.single()
        min_date = date_info[0] if date_info else "Unknown"
        max_date = date_info[1] if date_info else "Unknown"
        
        return {
            "label_context": label_context,
            "structure": structure,
            "date_range": {"min": min_date, "max": max_date}
        }

def get_cypher_from_question(question, schema):
    """
    Scalable Cypher Generation.
    """
    system_msg = f"""
    You are a Neo4j Cypher expert. Translate the user's question into a query using the DISCOVERED SCHEMA.
    
    SCHEMA CONTEXT:
    {json.dumps(schema['label_context'], indent=2)}
    
    VALID PATHS: {schema['structure']}
    DATE RANGE: {schema['date_range']['min']} to {schema['date_range']['max']}
    
    CRITICAL DIRECTIONAL LOGIC:
    Relationships ALWAYS point FROM the data nodes (News/Prices) TO the Material node.
    - (ns0__PriceObservation) --[:ns0__OBSERVED_FOR]--> (ns0__MaterialRequiredForProduction)
    - (ns0__Assertion) --[:ns0__RELATES_TO]--> (ns0__MaterialRequiredForProduction)
    
    LOGIC:
    1. Match Material names using 'rdfs__label'.
    2. THE ARROW MUST POINT TOWARDS THE MATERIAL NODE.
    3. If user says 'latest', use '{schema['date_range']['max']}'.
    4. Return ONLY a JSON object: {{"query": "MATCH ... RETURN ..."}}
    """
    
    result = invoke_bedrock_text(system_msg, question)
    if result and isinstance(result, dict):
        return result.get("query")
    return None

def summarize_answer(question, data):
    system_msg = """
    You are a supply chain analyst. Summarize the Neo4j data into a clear, natural language answer.
    DO NOT return raw JSON or dictionaries. Speak in professional full sentences.
    Mention specific dates, regions, and prices found in the data.
    Return JSON: {"answer": "..."}
    """
    context = f"Question: {question}\nData: {json.dumps(data)}"
    result = invoke_bedrock_text(system_msg, context)
    if isinstance(result, dict) and "answer" in result:
        return result["answer"]
    return str(data)

def chatbot():
    print("--- Apollo Semantic Chatbot (v11 - Enterprise Grade) ---")
    print("Type 'exit' to quit.")
    
    try:
        driver = GraphDatabase.driver(URI, auth=AUTH)
        logger.info("Initializing dynamic semantic graph engine...")
        schema = get_graph_schema(driver)
        
        while True:
            try:
                question = input("\nUser: ")
                if question.lower() in ['exit', 'quit']: break
                if not question.strip(): continue
                    
                print("Processing...")
                cypher = get_cypher_from_question(question, schema)
                if not cypher:
                    print("Bot: I'm sorry, I couldn't find a valid path in the graph to answer that question.")
                    continue
                    
                logger.info(f"Generated Cypher: {cypher}")
                
                with driver.session() as session:
                    result = session.run(cypher)
                    raw_data = [ {k: (dict(v) if hasattr(v, 'labels') else v) for k, v in record.items()} for record in result ]
                    
                    if not raw_data:
                        print("Bot: I couldn't find any data matching your request.")
                        continue
                        
                    print(f"\nBot: {summarize_answer(question, raw_data)}")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Bot: Something went wrong: {e}")
                    
        driver.close()
    except Exception as e:
        print(f"Bot: Connection error: {e}")
    print("\nBot: Goodbye!")

if __name__ == "__main__":
    chatbot()
