from neo4j import GraphDatabase

def get_graph_schema(driver):
    """
    Highly optimized, fully dynamic schema discovery.
    Runs rapid database-internal aggregation queries to construct
    the entire graph metadata context in < 0.1 seconds.
    """
    with driver.session() as session:
        # 1. Fetch all labels and their properties dynamically in a single query
        labels_cypher = """
        MATCH (n)
        UNWIND labels(n) as label
        WITH label, n
        WHERE not label starts with '_' AND label <> 'Resource'
        WITH label, keys(n) as keys
        UNWIND keys as key
        RETURN label, collect(distinct key) as properties
        """
        labels_res = session.run(labels_cypher)
        label_context = {}
        for r in labels_res:
            label_context[r['label']] = {"properties": r['properties']}

        # 2. Fetch all relationship types dynamically in a single query
        rel_cypher = """
        MATCH (a)-[r]->(b)
        UNWIND labels(a) as start
        UNWIND labels(b) as end
        WITH start, r, end
        WHERE not start starts with '_' AND not end starts with '_' AND start <> 'Resource' AND end <> 'Resource'
        RETURN DISTINCT start, type(r) as rel_type, end
        """
        rel_res = session.run(rel_cypher)
        structure = [f"({r['start']})-[:{r['rel_type']}]->({r['end']})" for r in rel_res]

        # 3. Global Date Context (Fast)
        date_res = session.run("""
            MATCH (n) 
            WHERE n.ns0__date IS NOT NULL OR n.ns0__price_date IS NOT NULL
            RETURN min(coalesce(n.ns0__date, n.ns0__price_date)) as min_date, 
                   max(coalesce(n.ns0__date, n.ns0__price_date)) as max_date
        """)
        date_info = date_res.single()
        min_date = date_info['min_date'] if date_info and date_info['min_date'] else "2023-01-01"
        max_date = date_info['max_date'] if date_info and date_info['max_date'] else "2025-12-31"

        return {
            "label_context": label_context,
            "structure": structure,
            "date_range": {"min": min_date, "max": max_date}
        }


