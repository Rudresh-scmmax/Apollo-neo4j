import os
import json
import boto3
import re

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
    if intent:
        intent_context = f"\nCLASSIFIED INTENT:\n{json.dumps(intent, indent=2)}\n"

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
       - If the user provides a text name, use regex: `m.rdfs__label =~ '(?i).*THE_NAME.*'`.
       - CRITICAL: Regex (`=~`) MUST be placed in the `WHERE` clause, NEVER inside the node brackets `{{}}`.
       - ALWAYS attach properties to the correct node: Prices/Dates belong to `ns0__BenchmarkPrice` or `ns0__TransactionPrice`. Material ID/Name belongs to `ns0__MaterialRequiredForProduction`.
    2. DYNAMIC NULL FILTERING: When the user asks for 'latest', 'recent', or specific values, ALWAYS add a `WHERE` clause to ensure the relevant properties are NOT NULL.
    3. DATA DICTIONARY:
       - Pricing: `(p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m:ns0__MaterialRequiredForProduction)`
       - News: `(e:ns0__MarketEvent)-[:ns0__affectsMaterial]->(m:ns0__MaterialRequiredForProduction)`
       - Transaction: `(t:ns0__TransactionPrice)-[:ns0__observedFor]->(m:ns0__MaterialRequiredForProduction)`
    4. OUTPUT FORMAT: OUTPUT ONLY THE CYPHER QUERY. NO PREAMBLE. NO EXPLANATION. NO CHATTER. DO NOT format as JSON.
       Example Query: MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m:ns0__MaterialRequiredForProduction) WHERE m.rdfs__label =~ '(?i).*THE_MATERIAL.*' AND p.ns0__price IS NOT NULL RETURN p.ns0__price ORDER BY p.ns0__price_date DESC LIMIT 1
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

