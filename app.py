from fastapi import FastAPI, Request, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from neo4j import GraphDatabase
from llm_module import get_embedding, invoke_bedrock_chat, generate_cypher
import json
import os
import shutil
import etl_pipeline
from schema_utils import get_graph_schema
from intent_system import IntentSystem

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

def run_dynamic_query(question):
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    
    # 1. Get Schema
    schema = get_graph_schema(driver)
    
    # 2. Get Intent
    print("[*] Classifying intent...")
    intent_system = IntentSystem()
    intent_obj = intent_system.process_question(question)
    
    # 3. Generate Cypher
    cypher = generate_cypher(question, schema, intent=intent_obj)
    print(f"GENERATED CYPHER: {cypher}")
    
    # 4. Execute
    results = []
    try:
        with driver.session() as session:
            embedding = get_embedding(question)
            print(f"Executing Cypher: {cypher}")
            try:
                res = session.run(cypher, embedding=embedding)
                for record in res:
                    item = record.data()
                    # Handle flexible column names from dynamic Cypher
                    parts = [f"{k}: {v}" for k, v in item.items() if v]
                    formatted = " | ".join(parts)
                    results.append(formatted)
                    print(f"Query Result: {formatted}")
            except Exception as e:
                print(f"Dynamic Cypher failed: {e}. Falling back to semantic search.")
            
            # 3.5 Secondary Recovery Scan (if 0 results and date-like query)
            if not results:
                print("Primary query returned 0 results. Attempting Deep Scan...")
                import re
                day_match = re.search(r'\b(0?[1-9]|[12][0-9]|3[01])\b', question)
                if day_match:
                    year_match = re.search(r'20\d{2}', question)
                    y = year_match.group() if year_match else "2025" # Default to 2025
                    d = day_match.group().zfill(2)
                    
                    months = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06", 
                              "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}
                    m = "01"
                    for name, code in months.items():
                        if name in question.lower():
                            m = code
                            break
                    
                    target_date = f"{y}-{m}-{d}"
                    print(f"Deep Scan Target Date: {target_date}")
                    recovery_cypher = f"""
                        MATCH (pe:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m) 
                        WHERE pe.ns0__price_date CONTAINS '{target_date}' 
                        RETURN pe.ns0__price as price, pe.ns0__price_date as date, pe.ns0__uom as uom, m.rdfs__label as material 
                        LIMIT 100
                    """
                    res = session.run(recovery_cypher)
                    for record in res:
                        item = record.data()
                        formatted = f"Price Point: {item['price']} {item['uom']} for {item['material']} on {item['date']}"
                        results.append(formatted)
                        print(f"Recovery Result: {formatted}")
            
            # FALLBACK: If no results or error, perform a wide vector search
            if not results:
                fallback_cypher = """
                CALL db.index.vector.queryNodes('assertion_index', 50, $embedding) YIELD node, score
                OPTIONAL MATCH (node)-[:ns0__isAbout]->(m)
                RETURN coalesce(node.ns0__content, node.ns0__snippetEvidence) as finding, 
                       coalesce(node.ns0__date, toString(node.ns0__assertionMadeAt)) as date, 
                       m.rdfs__label as material, score
                """
                res = session.run(fallback_cypher, embedding=embedding)
                for record in res:
                    results.append(f"Market Intelligence: {record['finding']} (Date: {record['date']}, Material: {record['material']})")

    except Exception as e:
        return f"System Error: {e}"
    finally:
        driver.close()
    
    return "\n".join(results[:200]) if results else "No direct graph matches found."

@app.get("/api/inventory")
async def get_inventory():
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        with driver.session() as session:
            # Query months and counts
            cypher = """
            MATCH (n:Resource)
            WHERE n:ns0__BenchmarkPrice OR n:ns0__MarketEvent OR n:ns0__Assertion
            WITH n, substring(coalesce(n.ns0__date, n.ns0__price_date, toString(n.ns0__assertionMadeAt)), 0, 7) as month
            WHERE month IS NOT NULL
            RETURN month,
                   count(DISTINCT CASE WHEN n:ns0__BenchmarkPrice THEN n END) as prices,
                   count(DISTINCT CASE WHEN n:ns0__MarketEvent THEN n END) as news,
                   count(DISTINCT CASE WHEN n:ns0__Assertion THEN n END) as takeaways
            ORDER BY month DESC
            """
            res = session.run(cypher)
            return [record.data() for record in res]
    finally:
        driver.close()

@app.get("/api/details/{month}")
async def get_details(month: str):
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        with driver.session() as session:
            # Prices
            price_res = session.run("""
                MATCH (pe:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)
                WHERE pe.ns0__price_date CONTAINS $month
                RETURN pe.uri as uri, pe.ns0__price as price, pe.ns0__price_date as date, 
                       pe.ns0__uom as uom, pe.ns0__region as region, 
                       m.rdfs__label as material, m.uri as material_uri
                ORDER BY date DESC
            """, month=month)
            
            # News
            news_res = session.run("""
                MATCH (me:ns0__MarketEvent)-[:ns0__affectsMaterial]->(m)
                WHERE me.ns0__date CONTAINS $month
                RETURN me.uri as uri, me.ns0__title as title, me.ns0__date as date, me.ns0__region as region, 
                       collect(DISTINCT m.rdfs__label) as materials, collect(DISTINCT m.uri) as material_uris
                ORDER BY date DESC
            """, month=month)
            
            # Takeaways
            takeaway_res = session.run("""
                MATCH (a:ns0__Assertion)-[:ns0__isAbout]->(m)
                WHERE coalesce(a.ns0__date, toString(a.ns0__assertionMadeAt)) CONTAINS $month
                RETURN a.uri as uri, 
                       coalesce(a.ns0__content, a.ns0__snippetEvidence) as content, 
                       coalesce(a.ns0__date, toString(a.ns0__assertionMadeAt)) as date, 
                       collect(DISTINCT m.rdfs__label) as materials, collect(DISTINCT m.uri) as material_uris
                ORDER BY date DESC
            """, month=month)
            
            return {
                "prices": [r.data() for r in price_res],
                "news": [r.data() for r in news_res],
                "takeaways": [r.data() for r in takeaway_res]
            }
    finally:
        driver.close()

@app.get("/api/validate")
async def run_validation(node_uri: str = None):
    shapes_file = "shapes.ttl"
    if not os.path.exists(shapes_file):
        return {"error": f"Shapes file {shapes_file} not found"}
        
    with open(shapes_file, 'r', encoding='utf-8') as f:
        shacl_data = f.read()
        
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        with driver.session() as session:
            # Import shapes inline
            session.run("CALL n10s.validation.shacl.import.inline($payload, 'Turtle')", payload=shacl_data)
            
            # Execute validation
            if node_uri:
                # Focused validation of target node and its relations
                query = """
                MATCH (n) WHERE n.uri = $node_uri
                OPTIONAL MATCH (n)-[r]-(m)
                WITH collect(DISTINCT n) + [x in collect(DISTINCT m) WHERE x IS NOT NULL] AS target_nodes
                CALL n10s.validation.shacl.validateSet(target_nodes)
                YIELD focusNode, nodeType, shapeId, propertyShape, offendingValue, resultPath, severity, resultMessage
                RETURN focusNode, nodeType, shapeId, propertyShape, offendingValue, resultPath, severity, resultMessage
                """
                res = session.run(query, node_uri=node_uri)
            else:
                # Full graph validation
                res = session.run("""
                CALL n10s.validation.shacl.validate()
                YIELD focusNode, nodeType, shapeId, propertyShape, offendingValue, resultPath, severity, resultMessage
                RETURN focusNode, nodeType, shapeId, propertyShape, offendingValue, resultPath, severity, resultMessage
                """)
                
            violations = [record.data() for record in res]
            return {"violations": violations, "validatedNode": node_uri}
    except Exception as e:
        return {"error": str(e)}
    finally:
        driver.close()

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
        If the data contains multiple price points or structured lists, ALWAYS use Markdown TABLES for clarity.
        If the data is empty, explain what you looked for but couldn't find.
        """
        
        answer = invoke_bedrock_chat(system_prompt, user_query)
        return {"response": answer}
        
    except Exception as e:
        return {"response": f"Backend error: {str(e)}"}

@app.post("/upload/ttl")
async def upload_ttl(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        file_path = "apollo5.ttl"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Trigger ETL Pipeline in background
        background_tasks.add_task(etl_pipeline.run_pipeline)
        
        return {"message": "Ontology uploaded successfully. Synchronization started in background."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Upload failed: {str(e)}"})

@app.post("/upload/pdf")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        # Ensure reports directory exists
        os.makedirs("reports", exist_ok=True)
        
        file_path = os.path.join("reports", file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Trigger ETL Pipeline in background
        background_tasks.add_task(etl_pipeline.run_pipeline)
        
        return {"message": f"Report '{file.filename}' uploaded. Ingestion started in background."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Upload failed: {str(e)}"})

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
