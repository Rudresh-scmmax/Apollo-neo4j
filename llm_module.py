import os
import json
import boto3
import re
from langchain_neo4j import Neo4jChatMessageHistory

# === AWS Bedrock Setup ===
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# Model IDs
TEXT_MODEL_ARN = "arn:aws:bedrock:us-east-1:127214171089:inference-profile/us.meta.llama4-scout-17b-instruct-v1:0"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"

def get_embedding(text):
    """
    Generate embedding using Amazon Titan v2.
    """
    try:
        body = json.dumps({"inputText": text})
        response = bedrock.invoke_model(
            modelId=EMBED_MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json"
        )
        response_body = json.loads(response['body'].read())
        return response_body.get("embedding")
    except Exception as e:
        print(f"Embedding failed: {e}")
        return None

def invoke_bedrock_text(system_msg, user_content, temperature=0.1, max_tokens=4096):
    """
    Invoke Bedrock's Llama 4 Scout text model using Converse API.
    """
    try:
        messages = [{"role": "user", "content": [{"text": user_content.strip()}]}]
        response = bedrock.converse(
            modelId=TEXT_MODEL_ARN,
            messages=messages,
            system=[{"text": system_msg.strip()}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature, "topP": 0.9}
        )
        
        text = ""
        if response.get('output') and response['output'].get('message'):
            content = response['output']['message'].get('content', [])
            if content and len(content) > 0:
                text = content[0].get('text', '')
        
        # Robust extraction: Find the first bracket ({ or [) and its matching partner
        first_obj = text.find("{")
        first_list = text.find("[")
        
        start_idx = -1
        open_b, close_b = "", ""
        
        if first_obj != -1 and (first_list == -1 or first_obj < first_list):
            start_idx, open_b, close_b = first_obj, "{", "}"
        elif first_list != -1:
            start_idx, open_b, close_b = first_list, "[", "]"
            
        if start_idx != -1:
            bracket_count = 0
            for i in range(start_idx, len(text)):
                if text[i] == open_b:
                    bracket_count += 1
                elif text[i] == close_b:
                    bracket_count -= 1
                    if bracket_count == 0:
                        json_text = text[start_idx : i + 1]
                        
                        # 1. Try standard JSON first
                        try:
                            return json.loads(json_text)
                        except json.JSONDecodeError:
                            pass
                            
                        # 2. Handle common LLM issues (trailing commas, single quotes around keys)
                        try:
                            # Remove trailing commas before closing brackets
                            cleaned = re.sub(r",\s*([}\]])", r"\1", json_text)
                            # Fix single quotes around keys/values only if NOT part of a Cypher string
                            # Instead of a dangerous regex, let's try a safer replacement for keys only
                            cleaned = re.sub(r"'(\w+)':", r'"\1":', cleaned)
                            return json.loads(cleaned)
                        except:
                            # Final fallback: just try to load the original block
                            try:
                                return json.loads(json_text.replace("'", '"'))
                            except:
                                return None
        return None
        
    except Exception as e:
        print(f"Bedrock invocation failed: {e}")
        return None


def generate_takeaways(extracted_text: str, material: str) -> str:
    """
    Extract key takeaways (6–8 points) for a given material.
    """
    system_msg = f"""
    You are a market analyst. Identify the publication, the published date (YYYY-MM-DD), and 6–8 bullet points for "{material}".
    Return EXACT JSON format:
    {{
        "publication": "...",
        "published_date": "YYYY-MM-DD",
        "takeaway_list": ["- takeaway 1", "- takeaway 2"]
    }}
    """
    data = invoke_bedrock_text(system_msg, extracted_text)
    if data and isinstance(data, dict):
        if "takeaway_list" not in data:
            for key in ["findings", "summary", "takeaways"]:
                if key in data:
                    data["takeaway_list"] = data.pop(key)
                    break
        return json.dumps(data)
    return json.dumps({"publication": "Unknown", "takeaway_list": []})

def news_agent(extracted_text, material, report_url):
    """
    Extract specific news related to the material.
    """
    system_msg = f"""
    You are a market intelligence agent. Extract all specific news events related to '{material}' from the provided text.
    Return your response ONLY as a JSON LIST of objects:
    [
      {{ "title": "...", "published_date": "YYYY-MM-DD", "region": "..." }}
    ]
    """
    try:
        news_list = invoke_bedrock_text(system_msg, extracted_text)
        if not isinstance(news_list, list):
            return []
        
        for item in news_list:
            item["news_url"] = report_url
            item["material"] = material
            if "region" in item and item["region"]:
                item["region"] = str(item["region"]).split(",")[-1].strip()
        return news_list
    except:
        return []

def invoke_bedrock_chat(system_msg, user_content, temperature=0.5):
    """
    Simple text-to-text chat invocation without JSON enforcement.
    """
    try:
        messages = [{"role": "user", "content": [{"text": user_content.strip()}]}]
        response = bedrock.converse(
            modelId=TEXT_MODEL_ARN,
            messages=messages,
            system=[{"text": system_msg.strip()}],
            inferenceConfig={"maxTokens": 2048, "temperature": temperature}
        )
        if response.get('output') and response['output'].get('message'):
            content = response['output']['message'].get('content', [])
            if content:
                return content[0].get('text', '')
        return "I encountered an error processing your request."
    except Exception as e:
        return f"Chat error: {e}"

def rewrite_query_with_context(user_query, session_id, neo4j_uri, neo4j_auth):
    """
    Rewrites a follow-up query using the conversational history stored in Neo4j.
    """
    try:
        history = Neo4jChatMessageHistory(
            url=neo4j_uri,
            username=neo4j_auth[0],
            password=neo4j_auth[1],
            session_id=session_id
        )
        
        # Get last 6 messages (3 turns)
        messages = history.messages[-6:]
        if not messages:
            return user_query # No history, return as is
            
        history_text = "\n".join([f"{m.type.capitalize()}: {m.content}" for m in messages])
        
        system_msg = f"""
        You are an intelligent query rewriter. Your job is to take a follow-up question and rewrite it into a fully self-contained question using the conversational history.
        
        CRITICAL RULES:
        1. Do NOT answer the question. ONLY output the rewritten query string.
        2. If the user's query is already self-contained, mentions a specific material (e.g., 'Acetic Acid'), or is a complete change of topic, you MUST return it EXACTLY as is. Do NOT merge it with the history.
        3. ONLY rewrite if the query contains a pronoun (e.g., 'it', 'they') or is clearly a vague follow-up (e.g., 'What about transaction prices?', 'Any news?'). In this case, inject the missing entity from the history.
        
        HISTORY:
        {history_text}
        """
        
        rewritten = invoke_bedrock_chat(system_msg, user_query, temperature=0.0)
        # Fallback: if the LLM completely ignored us and output something totally different but the query was already specific, we should ideally catch it, but returning the output is fine for now.
        return rewritten.strip(' "\'')
    except Exception as e:
        print(f"Query rewrite failed: {e}")
        return user_query

def price_by_date_agent(extracted_text, material):
    """
    Extracts price data by date.
    """
    system_msg = f"""
    You are a pricing analyst. Extract all price points mentioned for '{material}'.
    Return your response ONLY as a JSON LIST:
    [
      {{ "date": "2023-11-09", "price": "265-270", "price_type": "Spot", "uom": "mt", "region": "Asia", "extracted_material_name": "Glycerine Refined" }}
    ]
    """
    price_list = invoke_bedrock_text(system_msg, extracted_text)
    if isinstance(price_list, list):
        for p in price_list:
            if "region" in p and p["region"]:
                p["region"] = str(p["region"]).split(",")[-1].strip()
        return price_list
    return []

def generate_cypher(question, schema, intent=None):
    """
    LLM Agent that generates a Cypher query based on the database schema.
    """
    intent_context = ""
    semantic_rules_str = ""
    if intent:
        intent_context = f"\nCLASSIFIED INTENT:\n{json.dumps(intent, indent=2)}\n"
        if intent.get('semantic_rules'):
            rules_formatted = '\n'.join([f"       - {rule}" for rule in intent['semantic_rules']])
            semantic_rules_str = f"    4. DYNAMIC SEMANTIC RULES (MUST FOLLOW):\n{rules_formatted}"
        else:
            semantic_rules_str = "    4. DYNAMIC SEMANTIC RULES: None specific for this intent. Use schema below."

    # Build dynamic few-shot examples from live database entities
    samples = schema.get('sample_entities', {})
    s_name = samples.get('supplier', 'SupplierX')
    m_name = samples.get('material', 'MaterialY')
    p_name = samples.get('plant', 'PlantZ')

    dynamic_examples = f"""       Example 1 (Pricing/Highest Price): MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m), (p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude) WHERE (m.rdfs__label =~ '(?i).*{m_name}.*' OR m.uri =~ '(?i).*{m_name}.*') AND p.ns0__price_date IS NOT NULL RETURN p.ns0__price_date as date, mag.ns1__numericValue as price ORDER BY price DESC LIMIT 1
       Example 2 (Supplier Capacity - specific supplier): MATCH (sup:ns0__Supplier)-[rel:ns0__suppliesMaterial]->(m) WHERE sup.rdfs__label =~ '(?i).*{s_name}.*' RETURN sum(rel.ns0__capacity) as capacity
       Example 3 (Supplier Capacity - specific supplier + material): MATCH (sup:ns0__Supplier)-[rel:ns0__suppliesMaterial]->(m) WHERE sup.rdfs__label =~ '(?i).*{s_name}.*' AND (m.rdfs__label =~ '(?i).*{m_name}.*' OR m.uri =~ '(?i).*{m_name}.*') RETURN sum(rel.ns0__capacity) as capacity
       Example 4 (Plants Supplying a destination - ONLY join ProcurementSummary when filtering by plant): MATCH (sup:ns0__Supplier)<-[:ns0__providedBy]-(ps:ns0__ProcurementSummary)-[:ns0__deliveredTo]->(pl:ns0__PurchaserPlant), (ps)-[:ns0__procuredMaterial]->(m), (sup)-[rel:ns0__suppliesMaterial]->(m) WHERE pl.rdfs__label =~ '(?i).*{p_name}.*' AND (m.rdfs__label =~ '(?i).*{m_name}.*' OR m.uri =~ '(?i).*{m_name}.*') RETURN sum(rel.ns0__capacity) as capacity
       Example 5 (Comparing benchmark vs transaction price - minimum/maximum difference, aligned by month): MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m), (p)-[:ns0__hasMagnitude]->(p_mag:ns1__Magnitude), (s:ns0__ProcurementSummary)-[:ns0__procuredMaterial]->(m), (s)-[:ns0__hasTransactionPrice]->(t:ns0__TransactionPrice)-[:ns0__hasMagnitude]->(t_mag:ns1__Magnitude) WHERE (m.rdfs__label =~ '(?i).*{m_name}.*' OR m.uri =~ '(?i).*{m_name}.*') AND p.ns0__price_date >= '2024-01-01' AND p.ns0__price_date <= '2025-12-31' AND t.ns0__price_date IS NOT NULL AND p_mag.ns1__numericValue IS NOT NULL AND t_mag.ns1__numericValue IS NOT NULL AND substring(p.ns0__price_date, 0, 7) = substring(t.ns0__price_date, 0, 7) WITH p.ns0__price_date as date, p_mag.ns1__numericValue as benchmark_price, avg(t_mag.ns1__numericValue) as avg_transaction_price RETURN date, benchmark_price, avg_transaction_price, abs(benchmark_price - avg_transaction_price) as price_diff ORDER BY price_diff ASC LIMIT 1
       CRITICAL FOR PRICE COMPARISON: ALWAYS align benchmark and transaction prices by the same MONTH using `substring(p.ns0__price_date, 0, 7) = substring(t.ns0__price_date, 0, 7)`. Never do a raw cross-join. Use `WITH` to compute `avg(t_mag.ns1__numericValue)` per benchmark month before computing the diff.
       CRITICAL: Do NOT join with ProcurementSummary or PurchaserPlant when asking about a specific supplier's capacity. ProcurementSummary creates cartesian products (duplicating capacity values) because a supplier may have multiple POs. Only join ProcurementSummary when the question explicitly asks about deliveries to a specific PLANT/LOCATION."""

    system_msg = f"""
    You are a Neo4j Cypher Expert. Your task is to generate a Cypher query to answer the user's question.
    {intent_context}
    
    SCHEMA CONTEXT (Labels & Properties):
    {json.dumps(schema.get('label_context', {}), indent=2)}
    
    VALID GRAPH PATHS:
    {schema.get('structure', [])}
    
    TEMPORAL CONTEXT:
    Earliest data: {schema.get('date_range', {}).get('min', 'Unknown')}
    Latest data: {schema.get('date_range', {}).get('max', 'Unknown')}

    STRICT RULES:
    1. DYNAMIC MATERIAL MATCH: 
       - If the user provides a numeric ID, match EXACTLY using `m.ns0__material_id = 'THE_ID'`.
       - If the user provides a text name, use regex match on BOTH label and URI fragment: `(m.rdfs__label =~ '(?i).*THE_NAME.*' OR m.uri =~ '(?i).*THE_NAME.*')`.
       - CRITICAL: Some material nodes (like `http://api.stardog.com/Glycerine`) ONLY have labels `Resource` and `owl__NamedIndividual` and do NOT have the `ns0__MaterialRequiredForProduction` label or `rdfs__label` property. Therefore, do NOT specify label constraints on the material node `m` (i.e., use `(m)` instead of `(m:ns0__MaterialRequiredForProduction)`), and match using `(m.rdfs__label =~ '(?i).*THE_NAME.*' OR m.uri =~ '(?i).*THE_NAME.*')`.
       - CRITICAL: Regex (`=~`) MUST be placed in the `WHERE` clause, NEVER inside the node brackets `{{}}`.
       - ALWAYS attach properties to the correct node: Dates (e.g., `ns0__price_date` property) belong to `ns0__BenchmarkPrice` or `ns0__TransactionPrice`.
    2. MAGNITUDE PRICE VALUE: BenchmarkPrice and TransactionPrice do NOT have a direct price property. The actual numeric price value is in a related `ns1__Magnitude` node. 
       - You MUST join them using: `(p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)` and retrieve/filter on `mag.ns1__numericValue`.
    3. DYNAMIC NULL FILTERING: When the user asks for 'latest', 'recent', or specific values, ALWAYS add a `WHERE` clause to ensure the relevant properties (e.g. `p.ns0__price_date`, `mag.ns1__numericValue`) are NOT NULL.
{semantic_rules_str}
    5. NO DOUBLE WHERE CLAUSES: Never generate a query containing the `WHERE` keyword twice. Declare all paths in the MATCH clause (separated by commas) and put all conditions in a single WHERE clause using AND.
       - Example for disruptions: MATCH (e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m), (e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent) WHERE m.rdfs__label =~ '(?i).*{m_name}.*' AND toString(te.ns1__startDateTime) >= '2024-01-01' AND toString(te.ns1__endDateTime) <= '2024-12-31' RETURN e.rdfs__label as event, te.ns1__startDateTime as start_date, te.ns1__endDateTime as end_date
    6. OUTPUT FORMAT: OUTPUT ONLY THE CYPHER QUERY. NO PREAMBLE. NO EXPLANATION. NO CHATTER. DO NOT format as JSON.
    7. MATCH VS WHERE SYNTAX: ALL graph traversal relationships (like `(p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)`) MUST go in the MATCH clause separated by commas. NEVER place a relationship path inside a WHERE clause. The WHERE clause is strictly for properties.
{dynamic_examples}
    8. CYPHER SYNTAX RULES (CRITICAL):
       - DO NOT use Python-style comments (`#`). If you must comment, use Cypher-style `//`.
       - DO NOT write multiple `RETURN` statements in a single block. All variables must be returned in ONE single `RETURN` clause at the very end of the query.
       - A Cypher query MUST always conclude with a RETURN clause. NEVER conclude a query with a WITH clause. Always place a RETURN clause at the very end of the query to output the results.
       - NEVER use invalid time arithmetic like `183 days`. Use standard Neo4j duration functions like `duration('P6M')` for 6 months.
       - For dynamic date calculations relative to today, use `date() - duration('P6M')` or similar. Convert string date properties (like `p.ns0__price_date`) using `date()` before comparing them with other dates, for example: `WHERE date(p.ns0__price_date) >= date() - duration('P6M')`. Do NOT subtract a duration from `timestamp()`, and do NOT compare `DateTime` objects with `Long` timestamps.
       - PLACE OPTIONAL MATCH CLAUSES CORRECTLY: OPTIONAL MATCH clauses MUST come AFTER the main WHERE clause of the query. Writing a WHERE clause immediately after an OPTIONAL MATCH clause scopes that WHERE clause strictly to the OPTIONAL MATCH, which will NOT filter the main MATCH results!
         - Incorrect: MATCH (n) OPTIONAL MATCH (n)-[:rel]->(m) WHERE n.prop = 'val'
         - Correct: MATCH (n) WHERE n.prop = 'val' OPTIONAL MATCH (n)-[:rel]->(m)
       - A Cypher query MUST be a single unified query. DO NOT output multiple independent MATCH/RETURN blocks sequentially. If you need to search multiple patterns or event types (e.g., both supply disruptions and force majeure events for a company), you MUST combine them using `UNION` (ensuring every subquery has exactly the same column name returns in the same order) or chain them using `OPTIONAL MATCH`.
       - When matching companies or suppliers rather than materials, do not match them as materials. Use `ns0__Supplier` nodes (e.g., `(sup:ns0__Supplier) WHERE sup.rdfs__label =~ '(?i).*{s_name}.*'`). If searching assertions or reports for a company generally, search in the assertion's text itself: `MATCH (a:ns0__Assertion) WHERE a.rdfs__label =~ '(?i).*{s_name}.*' OR a.ns0__snippetEvidence =~ '(?i).*{s_name}.*' OPTIONAL MATCH (a)-[:ns0__assertedIn]->(r) RETURN a.rdfs__label as assertion, a.ns0__snippetEvidence as evidence, r.rdfs__label as report`.
    """
    
    # We use a lower temperature for code generation
    response = invoke_bedrock_chat(system_msg, question, temperature=0.0)
    
    # Clean up markdown if present
    cypher = response.replace("```cypher", "").replace("```", "").strip()
    
    # Extraction: If there is still preamble, try to find the first MATCH, CALL, or WITH
    match = re.search(r"(MATCH|CALL|WITH|CREATE|MERGE)[\s\S]*", cypher, re.I)
    if match:
        cypher = match.group().strip()
        
    cypher = fix_cypher_syntax(cypher)
    return cypher

def fix_cypher_syntax(cypher: str) -> str:
    """
    Self-healing Cypher syntax parser. Automatically corrects illegal LLM regex
    placements inside node brackets (e.g. {rdfs__label =~ '...'}) and moves them
    into valid WHERE clauses.
    """
    # Pattern 1: (var:Label {prop =~ 'regex'})
    pattern = r"\((\w+):([\w_]+)\s*\{\s*([\w_]+)\s*=~\s*('[^']+'|\"[^\"]+\")\s*\}\)"
    matches = re.findall(pattern, cypher)
    if matches:
        for var, label, prop, val in matches:
            brackets_str = f"{{{prop} =~ {val}}}"
            cypher = cypher.replace(brackets_str, "")
            if "WHERE" in cypher.upper():
                cypher = re.sub(r"(\bwhere\b)", f"WHERE {var}.{prop} =~ {val} AND", cypher, flags=re.IGNORECASE, count=1)
            else:
                kw_match = re.search(r"(\bwith\b|\breturn\b)", cypher, re.IGNORECASE)
                if kw_match:
                    idx = kw_match.start()
                    cypher = cypher[:idx] + f"WHERE {var}.{prop} =~ {val} \n" + cypher[idx:]
                else:
                    cypher += f"\nWHERE {var}.{prop} =~ {val}"
    # Auto-correct LLM stubbornly reversing observedFor direction
    cypher = re.sub(
        r"\((\w+)\)-\[:ns0__observedFor\]->\((\w+):ns0__BenchmarkPrice\)", 
        r"(\2:ns0__BenchmarkPrice)-[:ns0__observedFor]->(\1)", 
        cypher
    )
    cypher = re.sub(
        r"\((\w+)\)-\[:ns0__observedFor\]->\((\w+):ns0__TransactionPrice\)", 
        r"(\2:ns0__TransactionPrice)-[:ns0__observedFor]->(\1)", 
        cypher
    )
    # Auto-correct LLM chaining hasMagnitude to material instead of price node
    cypher = cypher.replace(")->(m)-[:ns0__hasMagnitude]", ")->(m), (p)-[:ns0__hasMagnitude]")
    cypher = cypher.replace("]->(m)-[:ns0__hasMagnitude]", "]->(m), (p)-[:ns0__hasMagnitude]")
                    
    # Pattern 2: (var:Label {prop: =~ 'regex'})
    pattern_colon = r"\((\w+):([\w_]+)\s*\{\s*([\w_]+)\s*:\s*=~\s*('[^']+'|\"[^\"]+\")\s*\}\)"
    matches_colon = re.findall(pattern_colon, cypher)
    if matches_colon:
        for var, label, prop, val in matches_colon:
            brackets_str = f"{{{prop}: =~ {val}}}"
            cypher = cypher.replace(brackets_str, "")
            if "WHERE" in cypher.upper():
                cypher = re.sub(r"(\bwhere\b)", f"WHERE {var}.{prop} =~ {val} AND", cypher, flags=re.IGNORECASE, count=1)
            else:
                kw_match = re.search(r"(\bwith\b|\breturn\b)", cypher, re.IGNORECASE)
                if kw_match:
                    idx = kw_match.start()
                    cypher = cypher[:idx] + f"WHERE {var}.{prop} =~ {val} \n" + cypher[idx:]
                else:
                    cypher += f"\nWHERE {var}.{prop} =~ {val}"
                    
    return cypher

