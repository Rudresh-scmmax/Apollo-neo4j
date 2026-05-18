import json
import logging
from llm_module import invoke_bedrock_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IntentSystem:
    def __init__(self):
        pass

    def decompose_question(self, question):
        """
        Decomposes a complex question into entities, timeframe, and core action.
        """
        system_msg = """
        You are a Question Decomposition Agent. Your goal is to break down a complex procurement or supply chain question into its atomic components.
        
        Extract the following:
        - materials: List of specific materials or products mentioned.
        - regions: List of geographical regions or countries.
        - timeframe: Any temporal references (e.g., 'last 3 months', 'Q1 2024').
        - core_actions: What the user wants to do (e.g., 'compare prices', 'find news', 'summarize trends').
        - is_complex: Boolean, true if the question has multiple distinct parts or intents.
        
        Return ONLY a JSON object:
        {
            "materials": [],
            "regions": [],
            "timeframe": "",
            "core_actions": [],
            "is_complex": false
        }
        """
        result = invoke_bedrock_text(system_msg, question)
        return result if result else {}

    def plan_classification(self, decomposition):
        """
        Decides which specialized classifiers to invoke.
        """
        system_msg = """
        You are a Classification Planner Agent. Based on the decomposition of a user's question, decide which intent domains are relevant.
        
        Intent Domains:
        - PRICING: For price trends, spot/contract prices, UOM, and currency.
        - MARKET_INTELLIGENCE: For news, disruptions, logistics, and supply chain events.
        - STRATEGIC_INSIGHT: For high-level assertions, takeaways, and market reports.
        
        Return ONLY a JSON object with a list of relevant domains:
        {
            "relevant_domains": ["PRICING", "MARKET_INTELLIGENCE"]
        }
        """
        context = json.dumps(decomposition)
        result = invoke_bedrock_text(system_msg, f"Decomposition: {context}")
        return result.get("relevant_domains", []) if result else []

    def classify_pricing(self, question, decomposition):
        system_msg = """
        You are a Pricing Intent Classifier. Identify specific pricing-related intents.
        Intents: price_check, price_trend, price_comparison, uom_inquiry.
        Return ONLY a JSON object: {"intent": "price_trend", "confidence": 0.9}
        """
        return invoke_bedrock_text(system_msg, question)

    def classify_market(self, question, decomposition):
        system_msg = """
        You are a Market Intelligence Classifier. Identify specific market-related intents.
        Intents: news_search, disruption_check, logistics_update, event_summary.
        Return ONLY a JSON object: {"intent": "news_search", "confidence": 0.9}
        """
        return invoke_bedrock_text(system_msg, question)

    def classify_strategic(self, question, decomposition):
        system_msg = """
        You are a Strategic Insight Classifier. Identify specific insight-related intents.
        Intents: takeaway_retrieval, assertion_search, trend_summary.
        Return ONLY a JSON object: {"intent": "takeaway_retrieval", "confidence": 0.9}
        """
        return invoke_bedrock_text(system_msg, question)

    def aggregate_intents(self, question, results):
        """
        Consolidates the outputs from multiple agents into a final intent.
        """
        system_msg = """
        You are an Intent Aggregator. You have the results from several specialized classification agents.
        Your job is to produce a single, coherent, and structured final intent object.
        
        Return ONLY a JSON object:
        {
            "primary_intent": "...",
            "secondary_intents": [],
            "entities": {
                "materials": [],
                "regions": [],
                "timeframe": ""
            },
            "summary": "Short explanation of the intent"
        }
        """
        context = json.dumps(results)
        return invoke_bedrock_text(system_msg, f"Question: {question}\nAgent Results: {context}")

    def process_question(self, question):
        logger.info(f"Processing question: {question}")
        
        # 1. Decompose
        decomposition = self.decompose_question(question)
        logger.info(f"Decomposition: {decomposition}")
        
        # 2. Plan
        domains = self.plan_classification(decomposition)
        logger.info(f"Planned domains: {domains}")
        
        # 3. Specialize
        agent_results = {"decomposition": decomposition}
        if "PRICING" in domains:
            agent_results["pricing"] = self.classify_pricing(question, decomposition)
        if "MARKET_INTELLIGENCE" in domains:
            agent_results["market"] = self.classify_market(question, decomposition)
        if "STRATEGIC_INSIGHT" in domains:
            agent_results["strategic"] = self.classify_strategic(question, decomposition)
            
        # 4. Aggregate
        final_intent = self.aggregate_intents(question, agent_results)
        logger.info(f"Final Intent: {final_intent}")
        
        return final_intent

if __name__ == "__main__":
    # Test
    system = IntentSystem()
    test_q = "What are the latest price trends for Glycerine in Asia and any recent disruptions?"
    print(json.dumps(system.process_question(test_q), indent=2))
