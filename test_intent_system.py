import json
from intent_system import IntentSystem

def test_intent_scenarios():
    system = IntentSystem()
    
    scenarios = [
        "What is the current price of Glycerine in Asia?",
        "Show me recent news about disruptions in the US supply chain for Methanol.",
        "Compare the price of Glycerine in Europe vs US for the last 6 months.",
        "What are the key takeaways from the latest market report on Caustic Soda?",
        "Are there any news on logistics issues for Glycerine and what is its price today?"
    ]
    
    print("Starting Multi-Agent Intent Classification Tests...\n")
    
    for q in scenarios:
        print(f"--- Testing Question: {q} ---")
        try:
            intent = system.process_question(q)
            print(json.dumps(intent, indent=2))
        except Exception as e:
            print(f"Error processing question: {e}")
        print("\n")

if __name__ == "__main__":
    test_intent_scenarios()
