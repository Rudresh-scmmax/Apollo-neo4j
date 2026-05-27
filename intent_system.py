import json
import logging
import os
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
        - MARKET_INTELLIGENCE: For news, disruptions, logistics, supply chain events, plant production, and supplier capacity.
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
        Intents: news_search, disruption_check, logistics_update, event_summary, capacity_inquiry.
        Return ONLY a JSON object: {"intent": "capacity_inquiry", "confidence": 0.9}
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
        
        CRITICAL RULES FOR INTENTS:
        The "primary_intent" and "secondary_intents" MUST be selected EXACTLY from this list:
        - "price_check": Finding specific price points (e.g., price on a date, latest price, min/max price, comparison to a static threshold).
        - "price_trend": Analyzing price trends or trends over time (e.g., 6 months trend).
        - "price_comparison": Comparing prices (e.g., benchmark vs transaction/purchase price, average comparisons, differences).
        - "uom_inquiry": Asking about UOM or units.
        - "capacity_inquiry": Inquiring about plant capacity or supplier capacity.
        - "list_plants": Listing plants receiving POs or materials.
        - "news_search": Searching for news, events, or logistics updates.
        - "disruption_check": Checking for supply disruptions or incidents.
        - "force_majeure_check": Checking for force majeure events.
        - "logistics_update": Checking for logistics, ports, or shipping issues.
        - "event_summary": Summarizing events or disruptions.
        - "takeaway_retrieval": Retrieving key takeaways or findings from reports.
        - "assertion_search": Searching for assertions or intelligence reports.
        - "trend_summary": Summarizing research/assertion trends.
        - "market outlook summary": Summarizing market outlook.
        
        Return ONLY a JSON object:
        {
            "primary_intent": "price_comparison",
            "secondary_intents": [],
            "entities": {
                "materials": ["Glycerine"],
                "regions": [],
                "timeframe": "2024"
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
        
        # 5. Semantic Layer Mapping
        try:
            with open(os.path.join(os.path.dirname(__file__), 'semantic_layer.json'), 'r') as f:
                semantic_layer = json.load(f)
            
            rules = []
            primary = final_intent.get('primary_intent', '')
            if primary in semantic_layer:
                rules.extend(semantic_layer[primary])
            for secondary in final_intent.get('secondary_intents', []):
                if secondary in semantic_layer:
                    rules.extend(semantic_layer[secondary])
                    
            final_intent['semantic_rules'] = list(set(rules))
        except Exception as e:
            logger.error(f"Failed to load semantic layer: {e}")
            final_intent['semantic_rules'] = []
            
        logger.info(f"Final Intent with Semantic Rules: {final_intent}")
        return final_intent

if __name__ == "__main__":
    # Test
    system = IntentSystem()
    test_q = "What are the latest price trends for Glycerine in Asia and any recent disruptions?"
    print(json.dumps(system.process_question(test_q), indent=2))
