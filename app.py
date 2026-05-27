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
from datetime import datetime
from langchain_neo4j import Neo4jChatMessageHistory
import uuid

# Global debug logs array
chat_logs = []

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

def run_dynamic_query(question, session_id="default"):
    from retrieval_validator import RetrievalValidator
    from context_compactor import ContextCompactor
    from agent_architectures import MultiAgentClassifier
    from llm_module import rewrite_query_with_context
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    
    # 0. Contextual Rewrite
    original_question = question
    print(f"[*] Original Question: {original_question}")
    question = rewrite_query_with_context(original_question, session_id, NEO4J_URI, NEO4J_AUTH)
    if question != original_question:
        print(f"[*] Rewritten Question: {question}")
    
    # 1. Get Schema
    schema = get_graph_schema(driver)
    
    # 2. Get Intent
    print("[*] Classifying intent...")
    intent_system = MultiAgentClassifier()
    intent_obj = intent_system.process_question(question)
    
    # 3. Generate Cypher
    cypher = generate_cypher(question, schema, intent=intent_obj)
    print(f"GENERATED CYPHER: {cypher}")
    
    records = []
    
    # 4. Execute and Validate
    try:
        validator = RetrievalValidator(NEO4J_URI, NEO4J_AUTH)
        compactor = ContextCompactor()
        
        with driver.session() as session:
            embedding = get_embedding(question)
            execution_error = None
            
            if cypher:
                print(f"Executing Cypher: {cypher}")
                try:
                    res = session.run(cypher, embedding=embedding)
                    for record in res:
                        records.append(record.data())
                except Exception as e:
                    execution_error = str(e)
                    print(f"Dynamic Cypher execution error: {e}")
            else:
                execution_error = "Cypher query generation failed."
                
            # Validate retrieved results
            validation = validator.validate(records, intent_obj) if not execution_error else {"is_valid": False, "reason": execution_error}
            
            # If invalid/empty, attempt Self-Healing
            if not validation["is_valid"]:
                print(f"Validation failed: {validation['reason']}. Triggering self-healing...")
                err_msg = execution_error or validation["reason"]
                healed_cypher, healed_records, report = validator.heal_and_execute(
                    question=question,
                    bad_cypher=cypher or "MATCH (n) RETURN n LIMIT 0",
                    error_msg=err_msg,
                    schema=schema,
                    intent=intent_obj
                )
                if report["status"] == "healed":
                    records = healed_records
                    print(f"Self-healing succeeded. Healed Cypher: {healed_cypher}")
                else:
                    print(f"Self-healing failed: {report['reason']}")
            
            # 5. Secondary Recovery Scan (if 0 results and date-like query)
            if not records:
                print("Primary query and healing returned 0 results. Attempting Deep Scan...")
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
                        records.append(record.data())
            
            # 6. FALLBACK: If no results or error, perform a wide vector search
            if not records:
                print("Running wide vector search fallback...")
                fallback_cypher = """
                CALL db.index.vector.queryNodes('assertion_index', 50, $embedding) YIELD node, score
                OPTIONAL MATCH (node)-[:ns0__isAbout]->(m)
                RETURN coalesce(node.ns0__content, node.ns0__snippetEvidence) as finding, 
                       coalesce(node.ns0__date, toString(node.ns0__assertionMadeAt)) as date, 
                       m.rdfs__label as material, score
                """
                res = session.run(fallback_cypher, embedding=embedding)
                for record in res:
                    records.append(record.data())

        # 7. Compact retrieved results into Markdown
        compacted = compactor.compact(question, records)
        
        # 8. Build Debug Log
        debug_log = {
            "timestamp": datetime.utcnow().isoformat(),
            "question": question,
            "original_question": original_question,
            "intent": intent_obj.get("primary_intent", "GENERAL"),
            "intent_extraction": intent_obj,
            "cypher": cypher,
            "response": compacted
        }
        
        # 9. Save to Neo4j Chat History
        try:
            history = Neo4jChatMessageHistory(
                url=NEO4J_URI,
                username=NEO4J_AUTH[0],
                password=NEO4J_AUTH[1],
                session_id=session_id
            )
            history.add_user_message(original_question)
            history.add_ai_message(compacted)
            
            # Save the debug log as a property on the last AI message
            with driver.session() as custom_sess:
                custom_sess.run("""
                    MATCH (s:Session {id: $session_id})-[:LAST_MESSAGE]->(m:Message {role: 'ai'})
                    SET m.debug_log = $debug_log
                """, session_id=session_id, debug_log=json.dumps(debug_log))
        except Exception as hist_e:
            print(f"Failed to save chat history: {hist_e}")
        
        return compacted, debug_log

    except Exception as e:
        print(f"run_dynamic_query failed: {e}")
        err_msg = f"System Error: {e}"
        err_log = {
            "timestamp": datetime.utcnow().isoformat(),
            "question": original_question if 'original_question' in locals() else question,
            "intent": "ERROR",
            "cypher": "NONE",
            "response": err_msg
        }
        try:
            history = Neo4jChatMessageHistory(
                url=NEO4J_URI,
                username=NEO4J_AUTH[0],
                password=NEO4J_AUTH[1],
                session_id=session_id
            )
            history.add_user_message(original_question if 'original_question' in locals() else question)
            history.add_ai_message(err_msg)
            
            with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as d:
                with d.session() as custom_sess:
                    custom_sess.run("""
                        MATCH (s:Session {id: $session_id})-[:LAST_MESSAGE]->(m:Message {role: 'ai'})
                        SET m.debug_log = $debug_log
                    """, session_id=session_id, debug_log=json.dumps(err_log))
        except Exception as hist_e:
            print(f"Failed to save error chat history: {hist_e}")
            
        return err_msg, err_log
    finally:
        driver.close()

@app.get("/api/inventory")
async def get_inventory():
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        with driver.session() as session:
            cypher = """
            MATCH (n:Resource)
            WHERE n:ns0__BenchmarkPrice OR n:ns0__SupplyDisruptionEvent
                  OR n:ns0__Assertion OR n:ns0__TransactionPrice
            WITH n,
                 substring(coalesce(
                     n.ns0__price_date,
                     n.ns0__published_date,
                     toString(n.ns0__assertionMadeAt)
                 ), 0, 7) as month
            WHERE month IS NOT NULL AND month <> ''
            RETURN month,
                   count(DISTINCT CASE WHEN n:ns0__BenchmarkPrice    THEN n END) as prices,
                   count(DISTINCT CASE WHEN n:ns0__SupplyDisruptionEvent THEN n END) as news,
                   count(DISTINCT CASE WHEN n:ns0__Assertion          THEN n END) as takeaways,
                   count(DISTINCT CASE WHEN n:ns0__TransactionPrice   THEN n END) as transactions
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
            # Benchmark Prices (join Magnitude for numeric value)
            price_res = session.run("""
                MATCH (pe:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m)
                WHERE pe.ns0__price_date CONTAINS $month
                OPTIONAL MATCH (pe)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)
                RETURN pe.uri as uri,
                       coalesce(toString(mag.ns1__numericValue), pe.ns0__price) as price,
                       pe.ns0__price_date as date,
                       coalesce(mag.ns1__unit, pe.ns0__currency) as currency,
                       pe.ns0__uom as uom, pe.ns0__region as region,
                       m.rdfs__label as material, m.uri as material_uri
                ORDER BY date DESC
            """, month=month)

            # Transaction Prices (PO history)
            tx_res = session.run("""
                MATCH (ps:ns0__ProcurementSummary)-[:ns0__procuredMaterial]->(m),
                      (ps)-[:ns0__hasTransactionPrice]->(tp:ns0__TransactionPrice)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)
                WHERE ps.ns0__purchase_date CONTAINS $month
                RETURN tp.uri as uri,
                       mag.ns1__numericValue as price,
                       ps.ns0__purchase_date as date,
                       mag.ns1__unit as currency,
                       ps.ns0__uom as uom,
                       ps.ns0__supplier_id as supplier,
                       ps.ns0__po_number as po_number,
                       ps.ns0__po_status as status,
                       ps.ns0__quantity as quantity,
                       m.rdfs__label as material, m.uri as material_uri
                ORDER BY date DESC
            """, month=month)

            # News / Disruption Events
            news_res = session.run("""
                MATCH (me:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m)
                WHERE me.ns0__published_date CONTAINS $month
                OPTIONAL MATCH (me)-[:ns0__hasLocation]->(geo)
                RETURN me.uri as uri, me.rdfs__label as title,
                       me.ns0__published_date as date,
                       geo.rdfs__label as region,
                       collect(DISTINCT m.rdfs__label) as materials,
                       collect(DISTINCT m.uri) as material_uris
                ORDER BY date DESC
            """, month=month)

            # Takeaways / Assertions
            takeaway_res = session.run("""
                MATCH (a:ns0__Assertion)-[:ns0__isAbout]->(m)
                WHERE toString(a.ns0__assertionMadeAt) CONTAINS $month
                RETURN a.uri as uri,
                       coalesce(a.ns0__snippetEvidence, a.ns0__content) as content,
                       toString(a.ns0__assertionMadeAt) as date,
                       a.ns0__publication as publication,
                       collect(DISTINCT m.rdfs__label) as materials,
                       collect(DISTINCT m.uri) as material_uris
                ORDER BY date DESC
            """, month=month)

            return {
                "prices":       [r.data() for r in price_res],
                "transactions": [r.data() for r in tx_res],
                "news":         [r.data() for r in news_res],
                "takeaways":    [r.data() for r in takeaway_res]
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
        session_id = data.get("session_id", "default")
        
        if not user_query:
            return {"response": "Please provide a query."}
        
        # 1. Dynamic Retrieval & Synthesis (Handled internally by Multi-Agent system)
        final_response, debug_log = run_dynamic_query(user_query, session_id)
        
        chat_logs.insert(0, debug_log)
        if len(chat_logs) > 50:
            chat_logs.pop()
        
        return {"response": final_response, "session_id": session_id}
        
    except Exception as e:
        return {"response": f"Backend error: {str(e)}"}

@app.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str):
    try:
        history = Neo4jChatMessageHistory(
            url=NEO4J_URI,
            username=NEO4J_AUTH[0],
            password=NEO4J_AUTH[1],
            session_id=session_id
        )
        # Format for frontend
        messages = []
        for msg in history.messages:
            messages.append({
                "role": msg.type,
                "content": msg.content
            })
        return {"messages": messages}
    except Exception as e:
        return {"error": str(e), "messages": []}

@app.get("/chat/sessions")
async def get_chat_sessions():
    """
    Get unique session IDs and titles from Neo4j memory, ordered chronologically.
    """
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        with driver.session() as session:
            # Match sessions, their latest message timestamp, and their first human question
            query = """
                MATCH (s:Session)
                OPTIONAL MATCH (s)-[:LAST_MESSAGE]->(latest:Message)
                OPTIONAL MATCH (latest)<-[:NEXT*0..100]-(msg:Message {role: 'human'})
                WITH s, latest, msg
                ORDER BY msg.createdAt ASC
                WITH s, latest, head(collect(msg.content)) as first_question
                ORDER BY latest.createdAt DESC
                RETURN s.id as session_id, first_question
                LIMIT 50
            """
            res = session.run(query)
            sessions = []
            for r in res:
                sid = r["session_id"]
                fq = r["first_question"]
                
                title = fq
                if title:
                    title = title.strip()
                    if len(title) > 28:
                        title = title[:25] + "..."
                else:
                    title = "General Chat" if sid == "default" else f"New Chat {sid[:6]}"
                
                sessions.append({
                    "id": sid,
                    "title": title
                })
            
            # If empty, return at least a default session
            if not sessions:
                sessions = [{"id": "default", "title": "General Chat"}]
            return {"sessions": sessions}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "sessions": [{"id": "default", "title": "General Chat"}]})

@app.delete("/chat/session/{session_id}")
async def delete_chat_session(session_id: str):
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        with driver.session() as session:
            session.run("""
                MATCH (s:Session {id: $session_id})
                OPTIONAL MATCH (s)-[:LAST_MESSAGE]->(latest:Message)
                OPTIONAL MATCH (latest)<-[:NEXT*0..100]-(msg:Message)
                DETACH DELETE s, latest, msg
            """, session_id=session_id)
        return {"status": "success", "message": f"Chat session {session_id} deleted successfully."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Failed to delete session: {str(e)}"})

@app.delete("/chat/sessions")
async def delete_all_chat_sessions():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        with driver.session() as session:
            session.run("""
                MATCH (s:Session)
                OPTIONAL MATCH (s)-[:LAST_MESSAGE]->(latest:Message)
                OPTIONAL MATCH (latest)<-[:NEXT*0..100]-(msg:Message)
                DETACH DELETE s, latest, msg
            """)
            session.run("""
                MATCH (m:Message)
                DETACH DELETE m
            """)
        return {"status": "success", "message": "All chat sessions and messages deleted successfully."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Failed to clear chats: {str(e)}"})

@app.get("/chat/logs/{session_id}")
async def get_session_logs(session_id: str):
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        with driver.session() as session:
            res = session.run("""
                MATCH (s:Session {id: $session_id})
                OPTIONAL MATCH (s)-[:LAST_MESSAGE]->(latest:Message)
                OPTIONAL MATCH (latest)<-[:NEXT*0..100]-(msg:Message {role: 'ai'})
                WHERE msg.debug_log IS NOT NULL
                RETURN msg.debug_log as debug_log, msg.createdAt as createdAt
                ORDER BY createdAt DESC
            """, session_id=session_id)
            logs = []
            for r in res:
                if r["debug_log"]:
                    try:
                        logs.append(json.loads(r["debug_log"]))
                    except Exception:
                        pass
            return logs
    except Exception as e:
        return {"error": str(e)}

@app.get("/logs")
async def get_logs():
    return chat_logs

@app.post("/upload/ttl")
async def upload_ttl(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload a new ontology TTL file and trigger a full ETL sync."""
    try:
        file_path = "apollo5.ttl"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        background_tasks.add_task(etl_pipeline.run_pipeline)
        return {"message": "Ontology uploaded successfully. Synchronization started in background."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Upload failed: {str(e)}"})


@app.post("/api/etl/sync")
async def trigger_etl_sync(background_tasks: BackgroundTasks, request: Request):
    """
    Trigger a PostgreSQL → Neo4j data sync in the background.
    Optionally accepts a JSON body with 'material_ids' list to restrict sync scope.
    Example body: {"material_ids": ["100724-000000", "102089-000000"]}
    Leave body empty to sync ALL materials.
    """
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        material_ids = body.get("material_ids", None)  # None = all materials
        background_tasks.add_task(etl_pipeline.run_pipeline, material_ids)
        scope = f"{len(material_ids)} materials" if material_ids else "all materials"
        return {"message": f"PSQL → Neo4j sync started in background ({scope})."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Sync trigger failed: {str(e)}"})


@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
