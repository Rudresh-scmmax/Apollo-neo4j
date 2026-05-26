import json
import logging
from llm_module import invoke_bedrock_text
from intent_system import IntentSystem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SingleAgentClassifier:
    """
    Architecture A: Single-Agent Zero-Shot.
    Classifies intent, entities, and summary in a single LLM call.
    """
    def __init__(self):
        pass

    def process_question(self, question: str) -> dict:
        system_msg = """
        You are a Zero-Shot Intent Classification Agent for a procurement knowledge graph.
        
        Analyze the question and classify the intents and entities.
        
        Intents to choose from:
        - PRICING: price_check, price_trend, price_comparison, uom_inquiry
        - MARKET_INTELLIGENCE: news_search, disruption_check, logistics_update, event_summary
        - STRATEGIC_INSIGHT: takeaway_retrieval, assertion_search, trend_summary
        
        Return ONLY a JSON object with this structure:
        {
            "primary_intent": "primary intent string (e.g. price_trend)",
            "secondary_intents": ["list of other intents detected"],
            "entities": {
                "materials": ["list of materials mentioned, e.g. Glycerine"],
                "regions": ["list of regions/countries, e.g. Asia"],
                "timeframe": "timeframe mentioned, e.g. latest, Q1 2024"
            },
            "summary": "short summary of user intent"
        }
        """
        try:
            logger.info("Executing Single-Agent Zero-Shot Classification...")
            result = invoke_bedrock_text(system_msg, question)
            return result if result else {}
        except Exception as e:
            logger.error(f"SingleAgentClassifier failed: {e}")
            return {}


class MultiAgentClassifier:
    """
    Architecture B: Multi-Agent Router.
    Uses decomposing, planning, specialized classifying, and aggregating agents.
    Wraps the existing IntentSystem.
    """
    def __init__(self):
        self.system = IntentSystem()

    def process_question(self, question: str) -> dict:
        logger.info("Executing Multi-Agent Routing Classification...")
        return self.system.process_question(question)


class ChainOfThoughtClassifier:
    """
    Architecture C: Chain-of-Thought Reasoning Agent.
    Generates step-by-step reasoning first, then outputs structured JSON classification.
    """
    def __init__(self):
        pass

    def process_question(self, question: str) -> dict:
        system_msg = """
        You are a Chain-of-Thought Intent Classification Agent for a procurement knowledge graph.
        
        Analyze the question step-by-step before producing your final classification.
        Provide a "Thinking:" section detailing your reasoning:
        1. Identify any materials (e.g. Glycerine, Caustic Soda) or entities.
        2. Identify geographical regions and timeframes (e.g. Asia, last 3 months).
        3. Identify whether pricing (spot prices, contract, trends), market events (news, logistics, disruptions), or strategic assertions (takeaways, insights) are being queried.
        4. Determine the primary intent and secondary intents.
        
        After your step-by-step thinking, output a final JSON object block:
        {
            "primary_intent": "primary intent",
            "secondary_intents": ["secondary intent list"],
            "entities": {
                "materials": ["materials"],
                "regions": ["regions"],
                "timeframe": "timeframe"
            },
            "summary": "summary description"
        }
        
        Example Output:
        Thinking:
        The user is asking about...
        Therefore, the intents are...
        
        {
            "primary_intent": "price_trend",
            "secondary_intents": ["disruption_check"],
            ...
        }
        """
        try:
            logger.info("Executing Chain-of-Thought Classification...")
            result = invoke_bedrock_text(system_msg, question)
            return result if result else {}
        except Exception as e:
            logger.error(f"ChainOfThoughtClassifier failed: {e}")
            return {}
