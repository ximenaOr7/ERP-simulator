"""
Agentes de Prospectos y Recomendación — Business Partners 
Materias: Inteligencia Artificial + CNO VI Sistemas ERP

Qué hace este script:
  1. Define un catálogo SIMULADO de socios de negocio (C = cliente, V = proveedor,
     L = prospecto/lead), productos y compras históricas.
  2. Ejecuta los agentes de prospectos:
       A1 Calificador de prospectos (lead scoring por reglas)
       A2 Detector de duplicados (tax_id / correo repetido)
       A3 Asesor de conversión L -> C (BP-RN05)
  3. Ejecuta los agentes de recomendación sobre un GRAFO:
       A4 Buscador de clientes similares (similitud de Jaccard)
       A5 Recomendador de productos (filtrado colaborativo basado en vecinos)
       A6 Selector de proveedor (activo, no bloqueado, menor tiempo de entrega)
       A7 Sugeridor de límite de crédito inicial (promedio ponderado de vecinos)
  4. Carga el grafo en Neo4j con MERGE + UNWIND (idempotente), corre las mismas
     consultas en Cypher y compara contra el cálculo en Python.

Modos:
  python src/neo4j_MATRICULA.py --offline   -> solo Python, sin servidor
  python src/neo4j_MATRICULA.py             -> Python + Neo4j (usa variables de entorno)
"""

from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# 1. Datos simulados
# ---------------------------------------------------------------------------

PRODUCTS = [
    {"sku": "PC-GAMER-01", "name": "Gaming PC Ryzen", "category": "GAMING_PC"},
    {"sku": "PC-OFICINA-01", "name": "PC de oficina", "category": "OFFICE_PC"},
    {"sku": "LAP-EDU-01", "name": "Laptop educativa", "category": "LAPTOP"},
    {"sku": "MON-27", "name": "Monitor 27 pulgadas", "category": "MONITOR"},
    {"sku": "SRV-01", "name": "Servidor rack", "category": "SERVER"},
    {"sku": "KIT-PERIF", "name": "Kit teclado y mouse", "category": "PERIPHERAL"},
    {"sku": "GPU-4070", "name": "Tarjeta gráfica", "category": "COMPONENT"},
    {"sku": "SSD-1TB", "name": "SSD 1 TB", "category": "COMPONENT"},
]

CLIENTS = [  # bp_type C
    {"card_code": "BP-C-101", "name": "Escuela Moderna (simulado)", "industry": "EDUCACION",
     "city": "San Luis Potosí", "active": True, "credit_limit_cents": 2000000,
     "tax_id": "SIMULADO-C-101", "email": "compras101@example.test",
     "bought": ["LAP-EDU-01", "KIT-PERIF", "MON-27"]},
    {"card_code": "BP-C-102", "name": "Ciber Arena (simulado)", "industry": "GAMING",
     "city": "San Luis Potosí", "active": True, "credit_limit_cents": 1500000,
     "tax_id": "SIMULADO-C-102", "email": "compras102@example.test",
     "bought": ["PC-GAMER-01", "MON-27", "GPU-4070"]},
    {"card_code": "BP-C-103", "name": "Despacho Contable (simulado)", "industry": "SERVICIOS",
     "city": "Querétaro", "active": True, "credit_limit_cents": 800000,
     "tax_id": "SIMULADO-C-103", "email": "compras103@example.test",
     "bought": ["PC-OFICINA-01", "KIT-PERIF"]},
    {"card_code": "BP-C-104", "name": "Universidad Centro (simulado)", "industry": "EDUCACION",
     "city": "Querétaro", "active": True, "credit_limit_cents": 5000000,
     "tax_id": "SIMULADO-C-104", "email": "compras104@example.test",
     "bought": ["LAP-EDU-01", "SRV-01", "MON-27"]},
    {"card_code": "BP-C-105", "name": "eSports Club (simulado)", "industry": "GAMING",
     "city": "Monterrey", "active": True, "credit_limit_cents": 1200000,
     "tax_id": "SIMULADO-C-105", "email": "compras105@example.test",
     "bought": ["PC-GAMER-01", "SSD-1TB", "KIT-PERIF"]},
    {"card_code": "BP-C-106", "name": "Hospital Norte (simulado)", "industry": "SALUD",
     "city": "San Luis Potosí", "active": False, "credit_limit_cents": 3000000,
     "tax_id": "SIMULADO-C-106", "email": "compras106@example.test",
     "bought": ["SRV-01", "PC-OFICINA-01"]},  # inactivo: BP-RN10, no cuenta como vecino
]

LEADS = [  # bp_type L
    {"card_code": "BP-L-101", "name": "Colegio Bilingüe (simulado)", "industry": "EDUCACION",
     "city": "San Luis Potosí", "employees": 80, "interactions": 4,
     "has_contact": True, "has_address": True,
     "tax_id": "SIMULADO-L-101", "email": "direccion@example.test",
     "interests": ["LAPTOP", "MONITOR"]},
    {"card_code": "BP-L-102", "name": "Torneos Gamer (simulado)", "industry": "GAMING",
     "city": "San Luis Potosí", "employees": 12, "interactions": 2,
     "has_contact": True, "has_address": False,
     "tax_id": "SIMULADO-L-102", "email": "torneos@example.test",
     "interests": ["GAMING_PC"]},
    {"card_code": "BP-L-103", "name": "Notaría Cinco (simulado)", "industry": "SERVICIOS",
     "city": "Querétaro", "employees": 8, "interactions": 1,
     "has_contact": False, "has_address": False,
     "tax_id": "SIMULADO-L-103", "email": "notaria@example.test",
     "interests": ["OFFICE_PC", "PERIPHERAL"]},
    {"card_code": "BP-L-104", "name": "Despacho Contable Sucursal (simulado)", "industry": "SERVICIOS",
     "city": "Querétaro", "employees": 5, "interactions": 1,
     "has_contact": True, "has_address": False,
     "tax_id": "SIMULADO-C-103", "email": "sucursal@example.test",  # mismo RFC que BP-C-103
     "interests": ["OFFICE_PC"]},
]

SUPPLIERS = [  # bp_type V
    {"card_code": "BP-V-101", "name": "Delta Componentes (simulado)", "active": True, "blocked_for": [],
     "supplies": [("GPU-4070", 5, 1450000), ("SSD-1TB", 3, 180000), ("PC-GAMER-01", 7, 3200000)]},
    {"card_code": "BP-V-102", "name": "Ensambles del Bajío (simulado)", "active": True, "blocked_for": [],
     "supplies": [("PC-GAMER-01", 4, 3350000), ("PC-OFICINA-01", 5, 1100000), ("SRV-01", 10, 6500000)]},
    {"card_code": "BP-V-103", "name": "Pantallas MX (simulado)", "active": True, "blocked_for": ["PURCHASES"],
     "supplies": [("MON-27", 3, 520000), ("KIT-PERIF", 2, 60000)]},  # bloqueado: BP-RN06
    {"card_code": "BP-V-104", "name": "EduTech Mayoreo (simulado)", "active": True, "blocked_for": [],
     "supplies": [("LAP-EDU-01", 6, 950000), ("MON-27", 4, 560000), ("KIT-PERIF", 3, 65000)]},
]

PRODUCT_BY_SKU = {p["sku"]: p for p in PRODUCTS}

# ---------------------------------------------------------------------------
# 2. Rasgos (features) para el grafo. Cada socio se conecta a nodos RecFeature:
#    industria, ciudad y categorías (compradas por clientes / de interés para leads)
# ---------------------------------------------------------------------------


def client_features(c: dict) -> list[str]:
    cats = sorted({PRODUCT_BY_SKU[s]["category"] for s in c["bought"]})
    return [f"industry:{c['industry']}", f"city:{c['city']}"] + [f"cat:{x}" for x in cats]


def lead_features(lead: dict) -> list[str]:
    return [f"industry:{lead['industry']}", f"city:{lead['city']}"] + [
        f"cat:{x}" for x in sorted(set(lead["interests"]))
    ]


# ---------------------------------------------------------------------------
# 3. Agentes de PROSPECTOS
# ---------------------------------------------------------------------------


def a2_find_duplicates(lead: dict) -> str | None:
    """A2: un prospecto es duplicado si su tax_id o correo ya existe en otro socio."""
    for other in CLIENTS + LEADS:
        if other["card_code"] == lead["card_code"]:
            continue
        if other["tax_id"] == lead["tax_id"] or other["email"] == lead["email"]:
            return other["card_code"]
    return None


def a1_score_lead(lead: dict) -> dict:
    """A1: calificación de 0 a 100 con reglas ponderadas."""
    active_industries = {c["industry"] for c in CLIENTS if c["active"]}
    catalog_cats = {p["category"] for p in PRODUCTS}
    detail = {
        "industria_con_clientes": 25 if lead["industry"] in active_industries else 0,
        "tiene_contacto": 15 if lead["has_contact"] else 0,
        "tiene_direccion": 10 if lead["has_address"] else 0,
        "tamano": 20 if lead["employees"] >= 50 else 10 if lead["employees"] >= 10 else 5,
        "interacciones": min(lead["interactions"] * 5, 20),
        "interes_en_catalogo": 10 if set(lead["interests"]) & catalog_cats else 0,
    }
    score = sum(detail.values())
    level = "HOT" if score >= 70 else "WARM" if score >= 40 else "COLD"
    return {"score": score, "level": level, "detail": detail}


def a3_conversion_advice(lead: dict, scoring: dict, duplicate_of: str | None) -> tuple[bool, str]:
    """A3: sugiere convertir L -> C solo si cumple todo (BP-RN05 conserva contactos/direcciones)."""
    if duplicate_of:
        return False, f"DUPLICADO de {duplicate_of}: fusionar, no convertir"
    if scoring["score"] < 70:
        return False, "Calificación menor a 70: seguir nutriendo el prospecto"
    if not lead["has_contact"]:
        return False, "Falta persona de contacto"
    if not lead["has_address"]:
        return False, "Falta dirección fiscal/de entrega"
    return True, "Listo para LEAD_CONVERTED (L -> C)"


# ---------------------------------------------------------------------------
# 4. Agentes de RECOMENDACIÓN — versión Python (referencia para validar Cypher)
# ---------------------------------------------------------------------------


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def a4_similar_clients(lead: dict, k: int) -> list[dict]:
    """A4: k clientes activos más parecidos al prospecto (Jaccard > 0)."""
    lf = set(lead_features(lead))
    sims = []
    for c in CLIENTS:
        if not c["active"]:
            continue
        s = jaccard(lf, set(client_features(c)))
        if s > 0:
            sims.append({"card_code": c["card_code"], "sim": round(s, 4)})
    sims.sort(key=lambda x: (-x["sim"], x["card_code"]))
    return sims[:k]


def a6_best_supplier(sku: str) -> dict | None:
    """A6: proveedor activo, no bloqueado para compras, con menor tiempo y luego menor precio."""
    options = []
    for v in SUPPLIERS:
        if not v["active"] or "PURCHASES" in v["blocked_for"]:
            continue
        for s, days, price in v["supplies"]:
            if s == sku:
                options.append((days, price, v["card_code"]))
    if not options:
        return None
    days, price, code = min(options)
    return {"supplier": code, "lead_days": days, "price_cents": price}


def a5_recommend(lead: dict, k: int, top: int) -> list[dict]:
    """A5: score(producto) = suma de similitudes de los vecinos que lo compraron."""
    neighbors = a4_similar_clients(lead, k)
    by_code = {c["card_code"]: c for c in CLIENTS}
    scores: dict[str, float] = {}
    via: dict[str, list[str]] = {}
    for n in neighbors:
        for sku in by_code[n["card_code"]]["bought"]:
            scores[sku] = scores.get(sku, 0.0) + n["sim"]
            via.setdefault(sku, []).append(n["card_code"])
    ranked = sorted(scores.items(), key=lambda x: (-round(x[1], 4), x[0]))[:top]
    return [
        {"sku": sku, "score": round(sc, 4), "via": sorted(via[sku]), "best_supplier": a6_best_supplier(sku)}
        for sku, sc in ranked
    ]


def a7_suggest_credit(neighbors: list[dict]) -> int:
    """A7: límite inicial = promedio de límites de los vecinos ponderado por similitud."""
    by_code = {c["card_code"]: c for c in CLIENTS}
    total_w = sum(n["sim"] for n in neighbors)
    if total_w == 0:
        return 0
    value = sum(by_code[n["card_code"]]["credit_limit_cents"] * n["sim"] for n in neighbors) / total_w
    return int(round(value / 10000) * 10000)  # redondeo a cientos de pesos


# ---------------------------------------------------------------------------
# 5. Neo4j: carga idempotente y mismas consultas en Cypher
# ---------------------------------------------------------------------------

CONSTRAINTS = [
    "CREATE CONSTRAINT rec_partner_code IF NOT EXISTS FOR (n:RecPartner) REQUIRE n.card_code IS UNIQUE",
    "CREATE CONSTRAINT rec_product_sku IF NOT EXISTS FOR (n:RecProduct) REQUIRE n.sku IS UNIQUE",
    "CREATE CONSTRAINT rec_feature_key IF NOT EXISTS FOR (n:RecFeature) REQUIRE n.key IS UNIQUE",
]

LOAD_PRODUCTS = """
UNWIND $rows AS row
MERGE (p:RecProduct {sku: row.sku})
SET p.name = row.name, p.category = row.category
"""

LOAD_CLIENTS = """
UNWIND $rows AS row
MERGE (c:RecPartner {card_code: row.card_code})
SET c.name = row.name, c.bp_type = 'C', c.industry = row.industry, c.city = row.city,
    c.active = row.active, c.credit_limit_cents = row.credit_limit_cents
WITH c, row
UNWIND row.bought AS sku
MATCH (p:RecProduct {sku: sku})
MERGE (c)-[:REC_BOUGHT]->(p)
"""

LOAD_LEADS = """
UNWIND $rows AS row
MERGE (l:RecPartner {card_code: row.card_code})
SET l.name = row.name, l.bp_type = 'L', l.industry = row.industry, l.city = row.city,
    l.active = true, l.employees = row.employees
"""

LOAD_FEATURES = """
UNWIND $rows AS row
MATCH (n:RecPartner {card_code: row.card_code})
UNWIND row.features AS key
MERGE (f:RecFeature {key: key})
MERGE (n)-[:REC_HAS_FEATURE]->(f)
"""

LOAD_SUPPLIERS = """
UNWIND $rows AS row
MERGE (v:RecPartner {card_code: row.card_code})
SET v.name = row.name, v.bp_type = 'V', v.active = row.active, v.blocked_for = row.blocked_for
WITH v, row
UNWIND row.supplies AS s
MATCH (p:RecProduct {sku: s.sku})
MERGE (v)-[r:REC_SUPPLIES]->(p)
SET r.lead_days = s.lead_days, r.price_cents = s.price_cents
"""

COUNT_NODES = """
MATCH (n) WHERE n:RecPartner OR n:RecProduct OR n:RecFeature
RETURN count(n) AS nodes
"""

COUNT_RELS = """
MATCH (:RecPartner)-[r]->() RETURN count(r) AS rels
"""

# A4 en Cypher: Jaccard = |intersección| / (|A| + |B| - |intersección|)
Q_SIMILAR = """
MATCH (l:RecPartner {card_code: $lead})-[:REC_HAS_FEATURE]->(f:RecFeature)
      <-[:REC_HAS_FEATURE]-(c:RecPartner {bp_type: 'C', active: true})
WITH l, c, count(f) AS inter
MATCH (l)-[:REC_HAS_FEATURE]->(lf)
WITH l, c, inter, count(lf) AS nl
MATCH (c)-[:REC_HAS_FEATURE]->(cf)
WITH c, inter, nl, count(cf) AS nc
WITH c, round(toFloat(inter) / (nl + nc - inter), 4) AS sim
RETURN c.card_code AS card_code, sim
ORDER BY sim DESC, card_code ASC
LIMIT $k
"""

# A5 + A6 en Cypher: vecinos -> productos comprados -> mejor proveedor permitido
Q_RECOMMEND = """
MATCH (l:RecPartner {card_code: $lead})-[:REC_HAS_FEATURE]->(f:RecFeature)
      <-[:REC_HAS_FEATURE]-(c:RecPartner {bp_type: 'C', active: true})
WITH l, c, count(f) AS inter
MATCH (l)-[:REC_HAS_FEATURE]->(lf)
WITH l, c, inter, count(lf) AS nl
MATCH (c)-[:REC_HAS_FEATURE]->(cf)
WITH c, inter, nl, count(cf) AS nc
WITH c, round(toFloat(inter) / (nl + nc - inter), 4) AS sim
ORDER BY sim DESC, c.card_code ASC
LIMIT $k
MATCH (c)-[:REC_BOUGHT]->(p:RecProduct)
WITH p, round(sum(sim), 4) AS score, collect(c.card_code) AS via
ORDER BY score DESC, p.sku ASC
LIMIT $top
OPTIONAL MATCH (v:RecPartner {bp_type: 'V', active: true})-[r:REC_SUPPLIES]->(p)
WHERE NOT 'PURCHASES' IN coalesce(v.blocked_for, [])
WITH p, score, via, v, r
ORDER BY r.lead_days ASC, r.price_cents ASC
WITH p, score, via,
     collect(CASE WHEN v IS NULL THEN NULL
                  ELSE {supplier: v.card_code, lead_days: r.lead_days, price_cents: r.price_cents} END) AS opts
RETURN p.sku AS sku, score, via, CASE WHEN size(opts) = 0 THEN NULL ELSE opts[0] END AS best_supplier
ORDER BY score DESC, sku ASC
"""

SAVE_RESULTS = """
MATCH (l:RecPartner {card_code: $lead})
SET l.lead_score = $score, l.lead_level = $level, l.duplicate_of = $duplicate_of,
    l.conversion_ready = $ready, l.suggested_credit_cents = $credit
WITH l
UNWIND $recs AS rec
MATCH (p:RecProduct {sku: rec.sku})
MERGE (l)-[r:REC_RECOMMENDED]->(p)
SET r.score = rec.score
"""


class Neo4jRepo:
    def __init__(self) -> None:
        from neo4j import GraphDatabase  # import tardío: el modo offline no lo necesita

        host = os.getenv("NEO4J_HOST", "localhost")
        port = os.getenv("NEO4J_PORT", "7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError("Falta NEO4J_PASSWORD en el entorno.")
        self.driver = GraphDatabase.driver(f"bolt://{host}:{port}", auth=(user, password))
        self.driver.verify_connectivity()

    def close(self) -> None:
        self.driver.close()

    def run(self, query: str, **params):
        records, _, _ = self.driver.execute_query(query, **params)
        return [r.data() for r in records]

    def setup(self) -> None:
        for c in CONSTRAINTS:
            self.run(c)

    def load(self) -> None:
        self.run(LOAD_PRODUCTS, rows=PRODUCTS)
        self.run(LOAD_CLIENTS, rows=CLIENTS)
        self.run(LOAD_LEADS, rows=LEADS)
        feats = [{"card_code": c["card_code"], "features": client_features(c)} for c in CLIENTS]
        feats += [{"card_code": l["card_code"], "features": lead_features(l)} for l in LEADS]
        self.run(LOAD_FEATURES, rows=feats)
        sup_rows = [
            {**{k: v[k] for k in ("card_code", "name", "active", "blocked_for")},
             "supplies": [{"sku": s, "lead_days": d, "price_cents": p} for s, d, p in v["supplies"]]}
            for v in SUPPLIERS
        ]
        self.run(LOAD_SUPPLIERS, rows=sup_rows)

    def counts(self) -> tuple[int, int]:
        return self.run(COUNT_NODES)[0]["nodes"], self.run(COUNT_RELS)[0]["rels"]


# ---------------------------------------------------------------------------
# 6. Orquestación y reporte
# ---------------------------------------------------------------------------


def money(cents: int) -> str:
    return f"${cents / 100:,.2f} MXN"


def run_agents(k: int, top: int) -> dict:
    results = {}
    for lead in LEADS:
        dup = a2_find_duplicates(lead)
        scoring = a1_score_lead(lead)
        ready, reason = a3_conversion_advice(lead, scoring, dup)
        neighbors = [] if dup else a4_similar_clients(lead, k)
        recs = [] if dup else a5_recommend(lead, k, top)
        credit = 0 if dup else a7_suggest_credit(neighbors)
        results[lead["card_code"]] = {
            "lead": lead, "duplicate_of": dup, "scoring": scoring, "ready": ready,
            "reason": reason, "neighbors": neighbors, "recs": recs, "credit": credit,
        }
    return results


def print_report(results: dict, highlight: str) -> None:
    print("=" * 72)
    print("AGENTES DE PROSPECTOS Y RECOMENDACIÓN — TechAssembly (datos simulados)")
    print("=" * 72)
    for code, r in results.items():
        mark = "  <== prospecto seleccionado" if code == highlight else ""
        print(f"\n[{code}] {r['lead']['name']}{mark}")
        print(f"  A1 Calificación: {r['scoring']['score']}/100 ({r['scoring']['level']}) {r['scoring']['detail']}")
        print(f"  A2 Duplicado: {r['duplicate_of'] or 'no'}")
        print(f"  A3 Conversión: {'SÍ' if r['ready'] else 'NO'} — {r['reason']}")
        if r["duplicate_of"]:
            print("  A4-A7 omitidos: un duplicado no recibe recomendaciones")
            continue
        print("  A4 Clientes similares: " + ", ".join(f"{n['card_code']} ({n['sim']})" for n in r["neighbors"]))
        for i, rec in enumerate(r["recs"], 1):
            sup = rec["best_supplier"]
            sup_txt = (f"{sup['supplier']}, {sup['lead_days']} días, {money(sup['price_cents'])}"
                       if sup else "sin proveedor disponible")
            print(f"  A5 #{i} {rec['sku']} ({PRODUCT_BY_SKU[rec['sku']]['name']}) score={rec['score']} "
                  f"por {rec['via']} | A6 proveedor: {sup_txt}")
        print(f"  A7 Crédito inicial sugerido: {money(r['credit'])}")


def same(py: list[dict], cy: list[dict], keys: list[str]) -> bool:
    if len(py) != len(cy):
        return False
    for a, b in zip(py, cy):
        for key in keys:
            va, vb = a.get(key), b.get(key)
            if isinstance(va, float) or isinstance(vb, float):
                if abs(float(va) - float(vb)) > 1e-3:
                    return False
            elif key == "via":
                if sorted(va) != sorted(vb):
                    return False
            elif va != vb:
                return False
    return True


def run_neo4j(results: dict, k: int, top: int) -> bool:
    repo = Neo4jRepo()
    ok = True
    try:
        print("\n" + "=" * 72)
        print("NEO4J — carga del grafo y validación")
        print("=" * 72)
        repo.setup()
        repo.load()
        first = repo.counts()
        repo.load()  # segunda carga: con MERGE no debe duplicar nada
        second = repo.counts()
        idem = first == second
        ok &= idem
        print(f"Nodos/relaciones tras 1a carga: {first} | tras 2a carga: {second} -> "
              f"{'IDEMPOTENTE' if idem else 'ERROR: hay duplicados'}")

        for code, r in results.items():
            if r["duplicate_of"]:
                continue
            cy_sim = repo.run(Q_SIMILAR, lead=code, k=k)
            cy_rec = repo.run(Q_RECOMMEND, lead=code, k=k, top=top)
            s_ok = same(r["neighbors"], cy_sim, ["card_code", "sim"])
            r_ok = same(r["recs"], cy_rec, ["sku", "score", "via", "best_supplier"])
            ok &= s_ok and r_ok
            print(f"{code}: similitud Cypher = Python -> {s_ok}; recomendación Cypher = Python -> {r_ok}")
            if not (s_ok and r_ok):
                print(f"   Python: {r['neighbors']} {r['recs']}")
                print(f"   Cypher: {cy_sim} {cy_rec}")

        for code, r in results.items():
            repo.run(SAVE_RESULTS, lead=code, score=r["scoring"]["score"], level=r["scoring"]["level"],
                     duplicate_of=r["duplicate_of"], ready=r["ready"], credit=r["credit"],
                     recs=[{"sku": x["sku"], "score": x["score"]} for x in r["recs"]])
        print("Resultados guardados en el grafo (propiedades del lead y relaciones REC_RECOMMENDED).")

        path = repo.run("""
            MATCH p = (l:RecPartner {card_code: 'BP-L-101'})-[:REC_HAS_FEATURE]->(:RecFeature)
                      <-[:REC_HAS_FEATURE]-(c:RecPartner {bp_type:'C'})-[:REC_BOUGHT]->(prod:RecProduct)
                      <-[:REC_SUPPLIES]-(v:RecPartner {bp_type:'V'})
            WHERE NOT 'PURCHASES' IN coalesce(v.blocked_for, [])
            RETURN [n IN nodes(p) | coalesce(n.card_code, n.sku, n.key)] AS ruta
            LIMIT 1
        """)
        if path:
            print("Ejemplo de ruta explicable en el grafo: " + " -> ".join(path[0]["ruta"]))
    finally:
        repo.close()
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentes de prospectos y recomendación con Neo4j")
    parser.add_argument("--offline", action="store_true", help="Solo cálculo en Python, sin Neo4j")
    parser.add_argument("--lead", default=os.getenv("LEAD_CODE", "BP-L-101"))
    parser.add_argument("--top", type=int, default=int(os.getenv("TOP_K", "3")))
    parser.add_argument("--neighbors", type=int, default=3)
    args = parser.parse_args()

    if args.lead not in {l["card_code"] for l in LEADS}:
        print(f"El prospecto {args.lead} no existe en el catálogo simulado.")
        return 1
    if args.top < 1:
        print("TOP_K debe ser mayor o igual a 1.")
        return 1

    results = run_agents(args.neighbors, args.top)
    print_report(results, args.lead)

    if args.offline:
        print("\nModo offline: no se usó Neo4j.")
        return 0

    ok = run_neo4j(results, args.neighbors, args.top)
    print("\nRESULTADO FINAL: " + ("OK" if ok else "FALLÓ LA VALIDACIÓN"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
