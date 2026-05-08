import os
import json
import boto3
import re

# === AWS Bedrock Setup ===
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# Model ARN
TEXT_MODEL_ARN = "arn:aws:bedrock:us-east-1:127214171089:inference-profile/us.meta.llama4-scout-17b-instruct-v1:0"

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
                        
                        # 1. Try standard JSON
                        try:
                            return json.loads(json_text)
                        except:
                            pass
                            
                        # 2. Try cleaning common issues (single quotes, trailing commas)
                        try:
                            # Replace single quotes with double quotes (basic)
                            cleaned = re.sub(r"'(.*?)'", r'"\1"', json_text)
                            return json.loads(cleaned)
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
