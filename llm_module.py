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

def generate_cypher(question, schema, material_context="Glycerine"):
    """
    LLM Agent that generates a Cypher query based on the database schema.
    """
    system_msg = f"""
    You are a Neo4j Cypher Expert. Generate a Cypher query to answer the user's question.
    
    SCHEMA:
    {schema}
    
    DATA DICTIONARY:
    - Materials: (m:ns0__MaterialRequiredForProduction)
    - Pricing: (pe:ns0__PriceEvent) linked to material via [:ns0__OBSERVED_FOR].
      Properties: pe.ns0__price, pe.ns0__price_date, pe.ns0__uom, pe.ns0__region
    - News/Disruptions: (me:ns0__MarketEvent) linked to material via [:ns0__IMPACTS].
      Properties: me.ns0__title, me.ns0__date, me.ns0__region
    - Findings/Takeaways: (a:ns0__Assertion) linked to material via [:ns0__RELATES_TO].
      Properties: a.ns0__content, a.ns0__date, a.ns0__publication

    CRITICAL RULES:
    1. NEVER put a 'WHERE' clause immediately after a 'RETURN'.
    2. Use 'ns0__' for ALL properties listed above.
    3. DATE FORMAT: Always convert user dates to 'YYYY-MM-DD'. In the query, use 'CONTAINS' for the date to be safe.
       GOOD: WHERE pe.ns0__price_date CONTAINS '2023-11-16'
    4. For 'price trends', always use ns0__PriceEvent and ns0__price_date.
    
    EXAMPLE - Price of Glycerine on a date:
    MATCH (m:ns0__MaterialRequiredForProduction) WHERE m.rdfs__label CONTAINS 'Glycerine'
    MATCH (pe:ns0__PriceEvent)-[:ns0__OBSERVED_FOR]->(m)
    WHERE pe.ns0__price_date CONTAINS '2023-11-16'
    RETURN pe.ns0__price, pe.ns0__uom, m.rdfs__label

    EXAMPLE - Market Disruptions (Vector Search):
    CALL db.index.vector.queryNodes('assertion_index', 10, $embedding) YIELD node AS n, score
    MATCH (n)-[:ns0__RELATES_TO]->(m:ns0__MaterialRequiredForProduction)
    RETURN n.ns0__content, n.ns0__date, m.rdfs__label
    ORDER BY n.ns0__date DESC
    """
    
    # We use a lower temperature for code generation
    cypher = invoke_bedrock_chat(system_msg, question, temperature=0.0)
    # Clean up any markdown blocks if the LLM adds them
    cypher = cypher.replace("```cypher", "").replace("```", "").strip()
    return cypher
