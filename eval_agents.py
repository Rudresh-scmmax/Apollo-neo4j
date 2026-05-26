import time
import json
import os
import logging
from neo4j import GraphDatabase
from agent_architectures import SingleAgentClassifier, MultiAgentClassifier, ChainOfThoughtClassifier
from context_compactor import ContextCompactor
from retrieval_validator import RetrievalValidator
from schema_utils import get_graph_schema
from llm_module import generate_cypher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Remote Neo4j Configuration
URI = "bolt://44.202.98.128:7687"
AUTH = ("neo4j", "neo4j@123")

# Test Queries Dataset
TEST_SUITE = [
    {
        "id": 1,
        "question": "What are the latest price trends for Glycerine in Asia?",
        "ground_truth": {
            "primary_intent": "price_trend",
            "materials": ["Glycerine"],
            "regions": ["Asia"]
        }
    },
    {
        "id": 2,
        "question": "Show me recent disruptions in Asia for Glycerine.",
        "ground_truth": {
            "primary_intent": "disruption_check",
            "materials": ["Glycerine"],
            "regions": ["Asia"]
        }
    },
    {
        "id": 3,
        "question": "What is the benchmark price for 100724-000000 in Asia-Pacific?",
        "ground_truth": {
            "primary_intent": "price_check",
            "materials": ["100724-000000"],
            "regions": ["Asia-Pacific"]
        }
    },
    {
        "id": 4,
        "question": "Are there any logistics updates or news events for Glycerine in 2024?",
        "ground_truth": {
            "primary_intent": "news_search",
            "materials": ["Glycerine"],
            "regions": []
        }
    },
    {
        "id": 5,
        "question": "What are the key takeaways or assertions for Glycerine Refined?",
        "ground_truth": {
            "primary_intent": "takeaway_retrieval",
            "materials": ["Glycerine Refined"],
            "regions": []
        }
    },
    {
        "id": 6,
        "question": "Find transaction prices and purchase history for Glycerine.",
        "ground_truth": {
            "primary_intent": "price_check",
            "materials": ["Glycerine"],
            "regions": []
        }
    }
]

def evaluate_architectures():
    print("\n" + "="*60)
    print("   APOLLO AGENT ARCHITECTURES BENCHMARK & EVALUATION   ")
    print("="*60)
    
    # Initialize classifiers
    single_agent = SingleAgentClassifier()
    multi_agent = MultiAgentClassifier()
    cot_agent = ChainOfThoughtClassifier()
    
    compactor = ContextCompactor()
    validator = RetrievalValidator(URI, AUTH)
    
    driver = None
    try:
        driver = GraphDatabase.driver(URI, auth=AUTH)
        driver.verify_connectivity()
        schema = get_graph_schema(driver)
        logger.info("Graph schema retrieved successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        return
        
    results_report = []
    
    # Aggregated metrics
    metrics = {
        "single": {"total_time": 0.0, "intent_correct": 0, "entities_correct": 0},
        "multi": {"total_time": 0.0, "intent_correct": 0, "entities_correct": 0},
        "cot": {"total_time": 0.0, "intent_correct": 0, "entities_correct": 0},
        "retrieval": {"raw_success": 0, "healed_success": 0, "total": 0},
        "compaction": {"total_raw_len": 0, "total_compact_len": 0}
    }
    
    for case in TEST_SUITE:
        q_id = case["id"]
        question = case["question"]
        gt = case["ground_truth"]
        
        print(f"\n[{q_id}/6] Evaluating Query: '{question}'")
        
        # --- Evaluate Single-Agent ---
        t0 = time.time()
        res_single = single_agent.process_question(question)
        dt_single = time.time() - t0
        metrics["single"]["total_time"] += dt_single
        
        # --- Evaluate Multi-Agent ---
        t0 = time.time()
        res_multi = multi_agent.process_question(question)
        dt_multi = time.time() - t0
        metrics["multi"]["total_time"] += dt_multi
        
        # --- Evaluate Chain-of-Thought ---
        t0 = time.time()
        res_cot = cot_agent.process_question(question)
        dt_cot = time.time() - t0
        metrics["cot"]["total_time"] += dt_cot
        
        # Accuracy checks
        def check_accuracy(res):
            if not res or not isinstance(res, dict):
                return False, False
            intent = res.get("primary_intent", "").lower()
            gt_intent = gt["primary_intent"].lower()
            intent_ok = (intent == gt_intent) or (gt_intent in intent) or (intent in gt_intent)
            
            entities = res.get("entities", {})
            mats = [m.lower() for m in entities.get("materials", [])]
            gt_mats = [m.lower() for m in gt["materials"]]
            entities_ok = any(m in mats for m in gt_mats) or any(m in gt_mats for m in mats)
            return intent_ok, entities_ok

        single_intent_ok, single_ent_ok = check_accuracy(res_single)
        multi_intent_ok, multi_ent_ok = check_accuracy(res_multi)
        cot_intent_ok, cot_ent_ok = check_accuracy(res_cot)
        
        if single_intent_ok: metrics["single"]["intent_correct"] += 1
        if single_ent_ok: metrics["single"]["entities_correct"] += 1
        if multi_intent_ok: metrics["multi"]["intent_correct"] += 1
        if multi_ent_ok: metrics["multi"]["entities_correct"] += 1
        if cot_intent_ok: metrics["cot"]["intent_correct"] += 1
        if cot_ent_ok: metrics["cot"]["entities_correct"] += 1
        
        # --- Cypher Gen, Retrieval, Validation & Healing ---
        # We will use Multi-Agent intent result for query generation
        chosen_intent = res_multi if res_multi else res_cot
        cypher = generate_cypher(question, schema, chosen_intent)
        print(f"  Generated Cypher: {cypher}")
        
        raw_results = []
        execution_error = None
        
        if cypher:
            try:
                with driver.session() as session:
                    # Run with dummy embedding or real embedding
                    from llm_module import get_embedding
                    emb = get_embedding(question)
                    db_res = session.run(cypher, embedding=emb)
                    for rec in db_res:
                        raw_results.append(rec.data())
            except Exception as e:
                execution_error = str(e)
                print(f"  Execution Error: {e}")
                
        metrics["retrieval"]["total"] += 1
        
        validation = validator.validate(raw_results, chosen_intent)
        retrieval_status = "Direct Success"
        healed_cypher = None
        
        if not validation["is_valid"]:
            # Trigger Self-Healing
            print(f"  Validation failed ({validation['reason']}). Triggering self-healing...")
            err = execution_error or "Empty retrieval / Entity validation failed."
            healed_cypher, healed_results, heal_report = validator.heal_and_execute(
                question=question,
                bad_cypher=cypher or "MATCH (n) RETURN n LIMIT 0",
                error_msg=err,
                schema=schema,
                intent=chosen_intent
            )
            if heal_report["status"] == "healed":
                raw_results = healed_results
                retrieval_status = f"Healed on attempt {heal_report['attempts']}"
                metrics["retrieval"]["healed_success"] += 1
            else:
                retrieval_status = f"Failed: {heal_report['reason']}"
        else:
            metrics["retrieval"]["raw_success"] += 1
            
        # --- Compaction ---
        raw_json_str = json.dumps(raw_results, default=str)
        compacted_context = compactor.compact(question, raw_results)
        
        raw_len = len(raw_json_str)
        compact_len = len(compacted_context)
        metrics["compaction"]["total_raw_len"] += raw_len
        metrics["compaction"]["total_compact_len"] += compact_len
        
        compaction_ratio = (1.0 - (compact_len / raw_len)) * 100 if raw_len > 2 else 0.0
        
        results_report.append({
            "id": q_id,
            "question": question,
            "single": {"time": dt_single, "intent_ok": single_intent_ok, "ent_ok": single_ent_ok},
            "multi": {"time": dt_multi, "intent_ok": multi_intent_ok, "ent_ok": multi_ent_ok},
            "cot": {"time": dt_cot, "intent_ok": cot_intent_ok, "ent_ok": cot_ent_ok},
            "retrieval_status": retrieval_status,
            "original_cypher": cypher,
            "healed_cypher": healed_cypher,
            "raw_length": raw_len,
            "compact_length": compact_len,
            "compaction_ratio": f"{compaction_ratio:.1f}%",
            "compacted_context": compacted_context
        })
        
    driver.close()
    
    # Generate the report
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/agent_evaluation_report.md"
    
    num_queries = len(TEST_SUITE)
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Apollo Knowledge Graph Agent Architecture Evaluation Report\n\n")
        f.write(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Executive Summary\n")
        f.write("This report benchmarks three intent classification architectures, validates Cypher query generation and retrieval, and measures the effectiveness of context compaction and self-healing mechanisms.\n\n")
        
        # Classification performance
        f.write("### 1. Classification Architectures Performance\n")
        f.write("| Metric | Architecture A: Single-Agent | Architecture B: Multi-Agent | Architecture C: Chain-of-Thought |\n")
        f.write("| --- | --- | --- | --- |\n")
        f.write(f"| **Avg Latency (s)** | {metrics['single']['total_time']/num_queries:.3f}s | {metrics['multi']['total_time']/num_queries:.3f}s | {metrics['cot']['total_time']/num_queries:.3f}s |\n")
        f.write(f"| **Intent Accuracy** | {metrics['single']['intent_correct']}/{num_queries} ({metrics['single']['intent_correct']/num_queries*100:.1f}%) | {metrics['multi']['intent_correct']}/{num_queries} ({metrics['multi']['intent_correct']/num_queries*100:.1f}%) | {metrics['cot']['intent_correct']}/{num_queries} ({metrics['cot']['intent_correct']/num_queries*100:.1f}%) |\n")
        f.write(f"| **Entity Accuracy** | {metrics['single']['entities_correct']}/{num_queries} ({metrics['single']['entities_correct']/num_queries*100:.1f}%) | {metrics['multi']['entities_correct']}/{num_queries} ({metrics['multi']['entities_correct']/num_queries*100:.1f}%) | {metrics['cot']['entities_correct']}/{num_queries} ({metrics['cot']['entities_correct']/num_queries*100:.1f}%) |\n\n")
        
        # Retrieval and healing performance
        f.write("### 2. Retrieval Validation & Self-Healing Performance\n")
        total_success = metrics["retrieval"]["raw_success"] + metrics["retrieval"]["healed_success"]
        f.write(f"- **Direct Retrieval Success Rate**: {metrics['retrieval']['raw_success']}/{num_queries} ({metrics['retrieval']['raw_success']/num_queries*100:.1f}%)\n")
        f.write(f"- **Self-Healed Retrieval Success Rate**: {metrics['retrieval']['healed_success']}/{num_queries} ({metrics['retrieval']['healed_success']/num_queries*100:.1f}%)\n")
        f.write(f"- **Overall Successful Retrieval Rate (Direct + Healed)**: {total_success}/{num_queries} ({total_success/num_queries*100:.1f}%)\n\n")
        
        # Compaction performance
        f.write("### 3. Context Compaction Compression\n")
        avg_raw = metrics["compaction"]["total_raw_len"] / num_queries
        avg_comp = metrics["compaction"]["total_compact_len"] / num_queries
        overall_compression = (1.0 - (metrics['compaction']['total_compact_len'] / metrics['compaction']['total_raw_len'])) * 100 if metrics['compaction']['total_raw_len'] > 0 else 0.0
        f.write(f"- **Avg Raw Context Size**: {avg_raw:.1f} characters\n")
        f.write(f"- **Avg Compacted Context Size**: {avg_comp:.1f} characters\n")
        f.write(f"- **Overall Compression/Compacting Ratio**: {overall_compression:.1f}%\n\n")
        
        # Detailed query cases
        f.write("## Detailed Evaluation Cases\n")
        for item in results_report:
            f.write(f"### Case {item['id']}: {item['question']}\n")
            f.write(f"- **Retrieval Status**: `{item['retrieval_status']}`\n")
            f.write("- **Classification Comparison**:\n")
            f.write(f"  - *Single-Agent*: Latency: {item['single']['time']:.2f}s | Intent Match: {item['single']['intent_ok']} | Entity Match: {item['single']['ent_ok']}\n")
            f.write(f"  - *Multi-Agent*: Latency: {item['multi']['time']:.2f}s | Intent Match: {item['multi']['intent_ok']} | Entity Match: {item['multi']['ent_ok']}\n")
            f.write(f"  - *Chain-of-Thought*: Latency: {item['cot']['time']:.2f}s | Intent Match: {item['cot']['intent_ok']} | Entity Match: {item['cot']['ent_ok']}\n")
            
            f.write(f"- **Generated Cypher**: `{item['original_cypher']}`\n")
            if item["healed_cypher"]:
                f.write(f"- **Healed Cypher**: `{item['healed_cypher']}`\n")
                
            f.write(f"- **Compaction Details**: Raw Len: {item['raw_length']} chars | Compact Len: {item['compact_length']} chars | Ratio: {item['compaction_ratio']}\n")
            f.write("- **Compacted Context Snippet**:\n")
            f.write(f"```markdown\n{item['compacted_context']}\n```\n\n")
            f.write("---\n\n")
            
    print(f"\n[+] Benchmarking complete. Evaluation report written to '{report_path}'.")

if __name__ == "__main__":
    evaluate_architectures()
