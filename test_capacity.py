import logging
from app import run_dynamic_query

logging.basicConfig(level=logging.INFO)

questions = [
    "What is the total capacity of Godrej plant?",
    "What is the total capacity of plants supplying to Mundra for Glycerine?"
]

for i, q in enumerate(questions):
    print(f"\n=== Test {i+1}: {q} ===")
    response = run_dynamic_query(q)
    print("Chatbot Response:")
    print(response)
    print("-" * 50)
