# Apollo Knowledge Graph Agent Architecture Evaluation Report

Generated at: 2026-05-26 07:30:14

## Executive Summary
This report benchmarks three intent classification architectures, validates Cypher query generation and retrieval, and measures the effectiveness of context compaction and self-healing mechanisms.

### 1. Classification Architectures Performance
| Metric | Architecture A: Single-Agent | Architecture B: Multi-Agent | Architecture C: Chain-of-Thought |
| --- | --- | --- | --- |
| **Avg Latency (s)** | 1.181s | 2.919s | 1.505s |
| **Intent Accuracy** | 5/6 (83.3%) | 5/6 (83.3%) | 2/6 (33.3%) |
| **Entity Accuracy** | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) |

### 2. Retrieval Validation & Self-Healing Performance
- **Direct Retrieval Success Rate**: 3/6 (50.0%)
- **Self-Healed Retrieval Success Rate**: 3/6 (50.0%)
- **Overall Successful Retrieval Rate (Direct + Healed)**: 6/6 (100.0%)

### 3. Context Compaction Compression
- **Avg Raw Context Size**: 21147.8 characters
- **Avg Compacted Context Size**: 1310.3 characters
- **Overall Compression/Compacting Ratio**: 93.8%

## Detailed Evaluation Cases
### Case 1: What are the latest price trends for Glycerine in Asia?
- **Retrieval Status**: `Healed on attempt 1`
- **Classification Comparison**:
  - *Single-Agent*: Latency: 1.51s | Intent Match: True | Entity Match: True
  - *Multi-Agent*: Latency: 2.95s | Intent Match: True | Entity Match: True
  - *Chain-of-Thought*: Latency: 1.04s | Intent Match: True | Entity Match: True
- **Generated Cypher**: `MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m), (p)-[:ns0__applicableLocation]->(geo:ns1__GeoLocation), (p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*') 
AND geo.rdfs__label = 'Asia' 
AND p.ns0__price_date IS NOT NULL 
AND mag.ns1__numericValue IS NOT NULL 
RETURN p.ns0__price_date as date, mag.ns1__numericValue as price 
ORDER BY date DESC 
LIMIT 1`
- **Healed Cypher**: `MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m), (p)-[:ns0__applicableLocation]->(geo:ns1__GeoLocation), (p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*') 
AND geo.rdfs__label =~ '(?i).*Asia.*' 
AND p.ns0__price_date IS NOT NULL 
AND mag.ns1__numericValue IS NOT NULL 
RETURN toString(p.ns0__price_date) as date, mag.ns1__numericValue as price 
ORDER BY date DESC 
LIMIT 1`
- **Compaction Details**: Raw Len: 41 chars | Compact Len: 55 chars | Ratio: -34.1%
- **Compacted Context Snippet**:
```markdown
| price | date |
| --- | --- |
| 1470.0 | 2026-03-19 |

```

---

### Case 2: Show me recent disruptions in Asia for Glycerine.
- **Retrieval Status**: `Healed on attempt 2`
- **Classification Comparison**:
  - *Single-Agent*: Latency: 0.79s | Intent Match: True | Entity Match: True
  - *Multi-Agent*: Latency: 2.74s | Intent Match: True | Entity Match: True
  - *Chain-of-Thought*: Latency: 1.56s | Intent Match: True | Entity Match: True
- **Generated Cypher**: `MATCH (e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m), (e)-[:ns0__hasLocation]->(loc:ns1__GeoRegion), (e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent)
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*')
AND loc.rdfs__label = 'Asia'
AND toString(te.ns1__startDateTime) >= '2022-01-01'
RETURN e.rdfs__label as event, te.ns1__startDateTime as start_date, te.ns1__endDateTime as end_date`
- **Healed Cypher**: `MATCH (e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m), (e)-[:ns0__hasLocation]->(loc:ns1__GeoRegion), (e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent)
WHERE m.rdfs__label =~ '(?i).*Glycerine.*'
AND loc.rdfs__label =~ '(?i).*Asia.*'
AND toString(te.ns1__startDateTime) >= '2022-01-01'
RETURN e.rdfs__label as event, te.ns1__startDateTime as start_date, te.ns1__endDateTime as end_date`
- **Compaction Details**: Raw Len: 77806 chars | Compact Len: 3000 chars | Ratio: 96.1%
- **Compacted Context Snippet**:
```markdown
### Recent Disruptions in Asia for Glycerine

#### Notable Events Impacting Glycerine Market in Asia:

* **2026-04-09**: Asia's glycerine market sees higher offers on concerns of US-Iran ceasefire.
* **2026-03-19**: 
  - Glycerine Prices Rise Amid Global Disruptions.
  - Spot offers for refined glycerine up on cost pressure.
  - Refined glycerine offers in a wide range at $1,050-1,110/tonne for December shipments.
* **2026-02-26**: 
  - Indonesia's export levy for crude glycerine to rise to 10%.
  - Glycerine spot offers revised up on demand.
* **2026-02-12**: 
  - Glycerine prices drop as demand wanes during festive holidays.
  - Downstream ECH market slows, prices down.
* **2026-02-05**: 
  - Indonesia export tax hike on crude glycerine to 10% boosts prices.
  - Crude glycerine up on Indonesia export tax hike to 10%.
* **2026-01-29**: 
  - Indonesia's export tax increase to impact glycerine market.
  - Glycerine spot offers rise on increased interest for March shipments.
  - Downstream ECH market remains bullish, supporting glycerine prices.
* **2026-01-22**: 
  - Indonesia's CPO export tax to rise to 12.5% from March.
  - Indonesia to raise crude glycerine export levy to 10% from March.
* **2025-11-27**: 
  - Downstream ECH market remains sluggish.
  - Crude glycerine buyers on sidelines as they cover December needs.
  - Glycerine Refined Drummed CFR Asia NE Spot price down $60/tonne.
* **2025-11-20**: 
  - Sluggish demand for refined glycerine from China.
  - Refined glycerine offers in a wide range at $1,050-1,110/tonne for December shipments.
  - Brazilian crude glycerine trades at $650-660/tonne CIF China.
* **2025-11-13**: 
  - Glycerine prices see slight rebound in late week due to higher bids.
  - Glycerine market sentiment remains low amid weak demand.
  - Weak demand and macroeconomic issues weigh on glycerine market sentiment.
* **2025-11-06**: Crude glycerine prices tumble on weak demand.
* **2025-10-30**: 
  - Downstream epichlorohydrin (ECH) falls lower.
  - Downstream ECH market remains sluggish.
  - Crude glycerine prices fall on waning spot interest.
  - Asia's refined glycerine market sees buy-sell tug-of-war.
* **2025-10-23**: 
  - Glycerine spot prices flat amid limited market participation.
  - US-China trade frictions weigh on glycerine demand.
  - Asia's crude glycerine market sees downward price pressure.
  - Crude glycerine imports from Latin America into China decrease.

#### Price Trends:

No specific price trends were provided in a format that could be directly converted into a markdown table. The data included various price mentions but not in a consistent or easily table-able format.

#### Conclusion:
The glycerine market in Asia has experienced various disruptions and trends influenced by factors such as export taxes, demand fluctuations, downstream market performance, and global economic conditions. These factors have led to price changes, shifts in market sentiment, and alterations in supply and demand dynamics.
```

---

### Case 3: What is the benchmark price for 100724-000000 in Asia-Pacific?
- **Retrieval Status**: `Direct Success`
- **Classification Comparison**:
  - *Single-Agent*: Latency: 0.72s | Intent Match: True | Entity Match: True
  - *Multi-Agent*: Latency: 2.71s | Intent Match: True | Entity Match: True
  - *Chain-of-Thought*: Latency: 1.86s | Intent Match: False | Entity Match: True
- **Generated Cypher**: `MATCH (p:ns0__BenchmarkPrice)-[:ns0__observedFor]->(m), (p)-[:ns0__applicableLocation]->(geo:ns1__GeoLocation), (m) 
WHERE m.ns0__material_id = '100724-000000' AND geo.rdfs__label = 'Asia-Pacific' 
MATCH (p)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude) 
WHERE p.ns0__price_date IS NOT NULL 
RETURN p.ns0__price_date as date, mag.ns1__numericValue as price ORDER BY date DESC LIMIT 1`
- **Compaction Details**: Raw Len: 41 chars | Compact Len: 55 chars | Ratio: -34.1%
- **Compacted Context Snippet**:
```markdown
| price | date |
| --- | --- |
| 1470.0 | 2026-03-19 |

```

---

### Case 4: Are there any logistics updates or news events for Glycerine in 2024?
- **Retrieval Status**: `Healed on attempt 1`
- **Classification Comparison**:
  - *Single-Agent*: Latency: 0.76s | Intent Match: False | Entity Match: True
  - *Multi-Agent*: Latency: 2.92s | Intent Match: True | Entity Match: True
  - *Chain-of-Thought*: Latency: 1.34s | Intent Match: False | Entity Match: True
- **Generated Cypher**: `MATCH (e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m), (e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*') 
AND toString(te.ns1__startDateTime) >= '2024-01-01' 
AND toString(te.ns1__endDateTime) <= '2024-12-31' 
RETURN e.rdfs__label as event, te.ns1__startDateTime as start_date, te.ns1__endDateTime as end_date 
UNION 
MATCH (e:ns0__ForceMajeureEvent)-[:ns0__affectsMaterial]->(m), (e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*') 
AND toString(te.ns1__startDateTime) >= '2024-01-01' 
AND toString(te.ns1__endDateTime) <= '2024-12-31' 
RETURN e.rdfs__label as event, te.ns1__startDateTime as start_date, te.ns1__endDateTime as end_date 
UNION 
MATCH (a:ns0__Assertion)-[:ns0__isAbout]->(m) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*') 
AND toString(a.ns0__assertionMadeAt) >= '2024-01-01' 
AND toString(a.ns0__assertionMadeAt) <= '2024-12-31' 
RETURN a.rdfs__label as event, a.ns0__assertionMadeAt as date 
ORDER BY date DESC`
- **Healed Cypher**: `MATCH (e:ns0__SupplyDisruptionEvent)-[:ns0__affectsMaterial]->(m), (e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*') 
AND toString(te.ns1__startDateTime) >= '2024-01-01' 
AND toString(te.ns1__endDateTime) <= '2024-12-31' 
RETURN e.rdfs__label as event, te.ns1__startDateTime as date 
UNION 
MATCH (e:ns0__ForceMajeureEvent)-[:ns0__affectsMaterial]->(m), (e)-[:ns0__hasTemporalExtent]->(te:ns1__TemporalExtent) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*') 
AND toString(te.ns1__startDateTime) >= '2024-01-01' 
AND toString(te.ns1__endDateTime) <= '2024-12-31' 
RETURN e.rdfs__label as event, te.ns1__startDateTime as date 
UNION 
MATCH (a:ns0__MarketEvent)-[:ns0__affectsMaterial]->(m) 
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*') 
AND toString(a.ns0__date) >= '2024-01-01' 
AND toString(a.ns0__date) <= '2024-12-31' 
RETURN a.rdfs__label as event, a.ns0__date as date 
ORDER BY date DESC`
- **Compaction Details**: Raw Len: 35996 chars | Compact Len: 2031 chars | Ratio: 94.4%
- **Compacted Context Snippet**:
```markdown
### Glycerine Logistics Updates and News Events in 2024

#### **Price Trends and Market Sentiment**
- **January 2024**: Glycerine spot prices rise on improved demand and upstream palm costs. The market sees increased spot interest amid anticipated price hikes.
- **February 2024**: Prices stable-to-firm on supply security concerns. Market lull ahead of Lunar New Year holiday.
- **March 2024**: Glycerine spot prices face upward pressure from pick-up in demand and rising production costs.
- **May 2024**: Prices drop on weak spot interest and slump in downstream ECH. 
- **July 2024**: Spot prices rise on improved demand and Red Sea crisis. 
- **August 2024**: Glycerine prices climb in Asia-Pacific on tight supply. 
- **October 2024**: Prices increase in Asia-Pacific due to tight supply and strong demand from HPC and food sectors.
- **November 2024**: Prices drop on sluggish ECH market.

#### **Supply and Demand**
- **January 2024**: Supply remains ample for refined glycerine; offers reduced to entice interest.
- **February 2024**: Glycerine market grinds to a standstill ahead of Lunar New Year.
- **May 2024**: Brazil floods impact soybean output, limit biodiesel supply. 
- **July 2024**: Downstream ECH capacities to expand in H2 2024.
- **August 2024**: Chinese spot interest picks up for Aug-Sept glycerine shipments.

#### **Logistics and External Factors**
- **February 2024**: Rising freight costs impact glycerine market.
- **May 2024**: Elevated freight rates and logistics issues challenge glycerine market.
- **June 2024**: Freight rates surge, impacting Q3 glycerine shipments.
- **July 2024**: Container freight rates to remain elevated near term for long-haul shipments.

#### **Key Events**
- **January 2024**: Indonesia may impose 200% tariff on Chinese textile imports.
- **May 2024**: China's GDP growth reaches 5.3% in Q1.
- **July 2024**: IMF upgrades China's growth forecast to 5% for 2024 and 4.5% for 2025.
- **December 2024**: Indonesia's B40 biodiesel mandate may take six months to implement.
```

---

### Case 5: What are the key takeaways or assertions for Glycerine Refined?
- **Retrieval Status**: `Direct Success`
- **Classification Comparison**:
  - *Single-Agent*: Latency: 0.72s | Intent Match: True | Entity Match: True
  - *Multi-Agent*: Latency: 2.70s | Intent Match: True | Entity Match: True
  - *Chain-of-Thought*: Latency: 1.30s | Intent Match: False | Entity Match: True
- **Generated Cypher**: `MATCH (a:ns0__Assertion)-[:ns0__isAbout]->(m) WHERE (m.rdfs__label =~ '(?i).*Glycerine Refined.*' OR m.uri =~ '(?i).*Glycerine Refined.*') RETURN a.rdfs__label as takeaway, a.ns0__snippetEvidence as evidence, a.ns0__assertionMadeAt as date`
- **Compaction Details**: Raw Len: 11188 chars | Compact Len: 2276 chars | Ratio: 79.7%
- **Compacted Context Snippet**:
```markdown
### Key Takeaways for Glycerine Refined

The following are key assertions and facts related to Glycerine Refined, synthesized into a concise bulleted list of facts with dates:

- **2023:**
  - **Sep 2023:** Typhoon Mawar caused Mindanao glycerine co-production to shut down.
  - **May 2023:** Gujarat load-shedding forced Mundra glycerine plant to reduce output.
  - **Mar 2023:** Sumatra flooding cut glycerine co-production in Q1.
  - **Feb 2023:** Turkey earthquake tightened refined glycerine availability into South Asia.
  - **Jul 2023:** Karachi port congestion delayed glycerine clearances.

- **2024:**
  - **Mar 2024:** Malaysia flooding reduced glycerine co-production from oleochemical refineries.
  - **Jun 2024:** IOI Prai boiler failure reduced glycerine spot availability.
  - **Jul 2024:** Mindanao earthquake suspended glycerine shipments from Davao.
  - **May 2024:** KLK Oleo Pasir Gudang fire forced glycerine supply force majeure.
  - **Sep 2024:** Red Sea disruption freight premium persisted.

- **2025:**
  - **Jan 2025:** 
    - Vadilal Mundra maintenance shutdown constrained spot glycerine.
    - Indonesia's B40 Biodiesel Mandate expected to boost glycerine co-production.
    - Caustic soda prices declined, reducing glycerine production input costs.
  - **Mar 2025:** 
    - Godrej Valia work stoppage removed Indian glycerine spot volumes.
    - US tariffs redirected Indian glycerine exports away from US buyers.
  - **May 2025:** North Sumatra earthquake shut glycerine co-production at Medan plants.
  - **Jul 2025:** Central Thailand floods shut biodiesel/glycerine plants.
  - **Sep 2025:** Musim Mas Batam force majeure on glycerine.
  - **Oct 2025:** Cyclone Yagi aftermath delayed TOL glycerine shipments.
  - **Nov 2025:** 
    - Wilmar's oleochemicals division margin was compressed by glycerine oversupply.
    - La Niña floods reduced Sabah CPO throughput and glycerine co-production.

- **2026:**
  - **Jan 2026:** China export licensing controls delayed glycerine supply and supported prices.

- **General:**
  - PFAD-CPO price spread is a key driver of glycerine producer economics.
  - IOI's new distillation line targets high-margin pharma-grade glycerine.
  - Global glycerine market facing structural oversupply in 2025-2026.
```

---

### Case 6: Find transaction prices and purchase history for Glycerine.
- **Retrieval Status**: `Direct Success`
- **Classification Comparison**:
  - *Single-Agent*: Latency: 2.58s | Intent Match: True | Entity Match: True
  - *Multi-Agent*: Latency: 3.49s | Intent Match: False | Entity Match: True
  - *Chain-of-Thought*: Latency: 1.92s | Intent Match: False | Entity Match: True
- **Generated Cypher**: `MATCH (m), (s:ns0__ProcurementSummary)-[:ns0__procuredMaterial]->(m), (s)-[:ns0__hasTransactionPrice]->(t:ns0__TransactionPrice)-[:ns0__hasMagnitude]->(mag:ns1__Magnitude)
WHERE (m.rdfs__label =~ '(?i).*Glycerine.*' OR m.uri =~ '(?i).*Glycerine.*') AND t.ns0__price_date IS NOT NULL AND mag.ns1__numericValue IS NOT NULL
RETURN 
  t.ns0__price_date as date, 
  mag.ns1__numericValue as price,
  s.ns0__po_number as po_number,
  s.ns0__supplier_id as supplier_id,
  s.ns0__purchase_date as purchase_date
ORDER BY date DESC`
- **Compaction Details**: Raw Len: 1815 chars | Compact Len: 445 chars | Ratio: 75.5%
- **Compacted Context Snippet**:
```markdown
### Glycerine Transaction Prices and Purchase History

| Date       | Price |
|------------|-------|
| 2023-06-15 | 0.5   |
| 2023-08-29 | 66.75 |
| 2023-11-29 | 42.5  |
| 2024-01-15 | 42.5  |
| 2024-02-07 | 42.5  |
| 2024-10-04 | 75.0  |
| 2025-03-03 | 90.0  |
| 2025-05-06 | 1.03  |
| 2025-05-11 | 73.5  |
| 2025-06-04 | 0.55  |
| 2025-06-12 | 56.0  |
| 2025-06-15 | 68.0  |
| 2025-06-17 | 95.0  |
| 2025-08-11 | 0.88  |
| 2025-09-30 | 56.5  |
```

---

