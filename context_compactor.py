import json
import logging
from llm_module import invoke_bedrock_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ContextCompactor:
    """
    Agent that takes large, noisy, or verbose graph/vector retrieval results
    and compacts them into a high-density, token-efficient markdown context.
    """
    def __init__(self):
        pass

    def compact(self, question: str, raw_data: list, use_llm: bool = True) -> str:
        """
        Main entry point for compacting raw query results.
        Supports both lists of dicts (from session.run) and lists of formatted strings.
        """
        if not raw_data:
            return "No data retrieved."

        # 1. Standardize input to a list of dicts if possible
        standardized_data = []
        for item in raw_data:
            if isinstance(item, dict):
                standardized_data.append(item)
            elif isinstance(item, str):
                # Try parsing as JSON or convert to simple dict
                try:
                    standardized_data.append(json.loads(item))
                except json.JSONDecodeError:
                    standardized_data.append({"raw_text": item})
            else:
                standardized_data.append({"value": str(item)})

        # 2. Heuristic preprocessing (deduplicate, remove noisy keys)
        cleaned_data = self._heuristic_preprocess(standardized_data)

        # 3. If dataset is small, output direct markdown.
        # If it is large or contains unstructured text, use LLM compaction.
        if len(cleaned_data) <= 5 and not any("raw_text" in d or "finding" in d or "content" in d for d in cleaned_data):
            logger.info("Data is small and structured; using heuristic Markdown representation.")
            return self._format_as_markdown(cleaned_data)
        
        if use_llm:
            logger.info(f"Invoking LLM Context Compactor for {len(cleaned_data)} records...")
            return self._llm_compact(question, cleaned_data)
        else:
            return self._format_as_markdown(cleaned_data)

    def _heuristic_preprocess(self, data: list) -> list:
        """
        Filters out internal metadata (like URIs or system fields) and deduplicates entries.
        """
        seen = set()
        cleaned = []
        
        # Keys to exclude from normal tabular representation if they clutter
        ignored_keys = {"uri", "material_uri", "material_uris", "po_number", "supplier_id"}

        for entry in data:
            # Create a frozen representation of the values to check for duplicates
            val_tuple = tuple(sorted((k, str(v)) for k, v in entry.items() if k not in ignored_keys))
            if val_tuple in seen:
                continue
            seen.add(val_tuple)

            # Filter out ignored keys
            filtered_entry = {k: v for k, v in entry.items() if k not in ignored_keys}
            cleaned.append(filtered_entry)

        return cleaned

    def _format_as_markdown(self, data: list) -> str:
        """
        Converts a list of dicts to a clean Markdown table.
        """
        if not data:
            return "No structured data."
        
        # Gather all unique keys across records to form columns
        headers = list(set().union(*(d.keys() for d in data)))
        if not headers:
            return "No columns to display."

        # Header Row
        markdown = "| " + " | ".join(headers) + " |\n"
        # Separator Row
        markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"
        
        # Data Rows
        for entry in data:
            row_vals = [str(entry.get(h, "")) for h in headers]
            markdown += "| " + " | ".join(row_vals) + " |\n"
            
        return markdown

    def _llm_compact(self, question: str, data: list) -> str:
        """
        Calls Bedrock to condense the dataset into a summary highlighting the relevant items.
        """
        system_msg = """
        You are a Context Compacting Agent. Your job is to take raw retrieval data (possibly containing duplicates, 
        internal identifiers, and verbose texts) and compact it into a dense, token-efficient, and readable markdown format.
        
        Guidelines:
        1. Keep only information that directly helps answer the user's question.
        2. If the data is numerical (e.g. price trends), format it as a markdown table sorted chronologically.
        3. If the data is text snippets (e.g. news/takeaways), synthesize them into a concise bulleted list of facts with dates.
        4. Exclude system identifiers, URIs, and duplicate records.
        5. DO NOT answer the question. Only output the compacted context block.
        """
        
        user_content = f"Question: {question}\nRaw Data:\n{json.dumps(data, default=str, indent=2)}"
        
        try:
            # We use invoke_bedrock_text but we need raw text. Wait! 
            # invoke_bedrock_text parses JSON. But we want a plain text markdown block.
            # Wait, let's see how invoke_bedrock_text works:
            # It looks for '{' or '[' and parses it. If we want raw text, can we use invoke_bedrock_chat?
            # Yes! invoke_bedrock_chat does not enforce JSON parsing and returns the raw string.
            from llm_module import invoke_bedrock_chat
            compacted_text = invoke_bedrock_chat(system_msg, user_content, temperature=0.1)
            return compacted_text
        except Exception as e:
            logger.error(f"LLM compaction failed: {e}. Falling back to markdown table.")
            return self._format_as_markdown(data)
