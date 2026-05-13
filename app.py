from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from neo4j import GraphDatabase
from llm_module import get_embedding, invoke_bedrock_chat, generate_cypher
import json
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
NEO4J_URI = "bolt://44.202.98.128:7687"
NEO4J_AUTH = ("neo4j", "neo4j@123")

def get_db_schema():
    """
    Fetches the current database schema labels and relationships.
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    schema = {"labels": [], "relationships": []}
    try:
        with driver.session() as session:
            labels_res = session.run("CALL db.labels()")
            schema["labels"] = [r[0] for r in labels_res]
            
            rels_res = session.run("CALL db.relationshipTypes()")
            schema["relationships"] = [r[0] for r in rels_res]
    finally:
        driver.close()
    return json.dumps(schema)

def run_dynamic_query(question):
    # 1. Get Schema
    schema = get_db_schema()
    
    # 2. Generate Cypher
    cypher = generate_cypher(question, schema)
    print(f"GENERATED CYPHER: {cypher}")
    
    # 3. Execute
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    results = []
    try:
        with driver.session() as session:
            embedding = get_embedding(question)
            print(f"Executing Cypher: {cypher}")
            try:
                res = session.run(cypher, embedding=embedding)
                for record in res:
                    data = record.data()
                    print(f"Query Result: {data}")
                    results.append(str(data))
            except Exception as e:
                print(f"Dynamic Cypher failed: {e}. Falling back to semantic search.")
            
            # 3.5 Secondary Recovery Scan (if 0 results and date-like query)
            if not results and "20" in question:
                print("Primary query returned 0 results. Attempting Deep Scan...")
                # Extract date components to build a YYYY-MM-DD string
                import re
                # Try to find year, month, day
                year_match = re.search(r'20\d{2}', question)
                day_match = re.search(r'\b(0?[1-9]|[12][0-9]|3[01])\b', question)
                if year_match and day_match:
                    y = year_match.group()
                    d = day_match.group().zfill(2)
                    # Simple month mapping
                    months = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06", 
                              "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}
                    m = "01"
                    for name, code in months.items():
                        if name in question.lower():
                            m = code
                            break
                    
                    target_date = f"{y}-{m}-{d}"
                    print(f"Deep Scan Target Date: {target_date}")
                    recovery_cypher = f"MATCH (p:ns0__PriceEvent) WHERE p.ns0__price_date CONTAINS '{target_date}' RETURN p.ns0__price, p.ns0__price_date, p.ns0__uom LIMIT 5"
                    res = session.run(recovery_cypher)
                    for record in res:
                        results.append(str(record.data()))
                        print(f"Recovery Result: {record.data()}")
            
            # FALLBACK: If no results or error, perform a wide vector search
            if not results:
                fallback_cypher = """
                CALL db.index.vector.queryNodes('assertion_index', 10, $embedding) YIELD node, score
                OPTIONAL MATCH (node)-[:ns0__RELATES_TO]->(m)
                RETURN node.ns0__content as finding, node.ns0__date as date, m.rdfs__label as material, score
                """
                res = session.run(fallback_cypher, embedding=embedding)
                for record in res:
                    results.append(f"Finding: {record['finding']} (Date: {record['date']}, Material: {record['material']})")

    except Exception as e:
        return f"System Error: {e}"
    finally:
        driver.close()
    
    return "\n".join(results[:10]) if results else "No direct graph matches found."

@app.post("/chat")
async def chat(request: Request):
    try:
        data = await request.json()
        user_query = data.get("query", "")
        
        if not user_query:
            return {"response": "Please provide a query."}
        
        # 1. Dynamic Retrieval
        graph_data = run_dynamic_query(user_query)
        
        # 2. LLM Synthesis
        system_prompt = f"""
        You are the Apollo Procurement Intelligence Assistant. 
        You have analyzed the knowledge graph and found the following raw data:
        
        --- RAW GRAPH DATA ---
        {graph_data}
        ----------------------
        
        Answer the user's question professionally using this data. 
        If the data is empty, explain what you looked for but couldn't find.
        """
        
        answer = invoke_bedrock_chat(system_prompt, user_query)
        return {"response": answer}
        
    except Exception as e:
        return {"response": f"Backend error: {str(e)}"}

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
