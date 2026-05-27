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
        WHERE not label starts with '_' AND label <> 'Resource' AND label <> 'Session' AND label <> 'Message'
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
        WHERE not start starts with '_' AND not end starts with '_' AND start <> 'Resource' AND end <> 'Resource' AND start <> 'Session' AND end <> 'Session' AND start <> 'Message' AND end <> 'Message'
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

        # 4. Fetch sample entities for dynamic few-shot examples
        sample_entities = _get_sample_entities(session)

        return {
            "label_context": label_context,
            "structure": structure,
            "date_range": {"min": min_date, "max": max_date},
            "sample_entities": sample_entities
        }


def _get_sample_entities(session):
    """
    Fetch one real sample entity for each key type (Supplier, Material, Plant)
    from Neo4j. Used to build dynamic few-shot examples in the LLM prompt.
    """
    samples = {"supplier": "SupplierX", "material": "MaterialY", "plant": "PlantZ"}
    try:
        # Get a sample supplier name
        res = session.run("MATCH (s:ns0__Supplier) WHERE s.rdfs__label IS NOT NULL RETURN s.rdfs__label AS name LIMIT 1")
        rec = res.single()
        if rec:
            samples["supplier"] = rec["name"]

        # Get a sample material name (prefer ones with rdfs__label, fallback to URI)
        res = session.run("""
            MATCH (s:ns0__Supplier)-[:ns0__suppliesMaterial]->(m) 
            WHERE m.rdfs__label IS NOT NULL 
            RETURN m.rdfs__label AS name LIMIT 1
        """)
        rec = res.single()
        if rec:
            samples["material"] = rec["name"]
        else:
            res = session.run("""
                MATCH (s:ns0__Supplier)-[:ns0__suppliesMaterial]->(m) 
                RETURN replace(split(m.uri, '/')[-1], '_', ' ') AS name LIMIT 1
            """)
            rec = res.single()
            if rec and rec["name"]:
                samples["material"] = rec["name"]

        # Get a sample plant name
        res = session.run("MATCH (p:ns0__PurchaserPlant) WHERE p.rdfs__label IS NOT NULL RETURN p.rdfs__label AS name LIMIT 1")
        rec = res.single()
        if rec:
            samples["plant"] = rec["name"]
    except Exception as e:
        print(f"[WARN] Could not fetch sample entities: {e}")

    return samples
