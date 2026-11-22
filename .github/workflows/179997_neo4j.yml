name: 179997 - Neo4j Prospectos y Recomendacion

on:
  push:
    branches:
      - feature/179997
    paths:
      - "src/neo4j_179997.py"
      - ".github/workflows/179997_neo4j.yml"
  workflow_dispatch:
    inputs:
      lead_code:
        description: "Prospecto a analizar (BP-L-101, BP-L-102, BP-L-103, BP-L-104)"
        required: true
        default: "BP-L-101"
      top_k:
        description: "Cantidad de productos a recomendar"
        required: true
        default: "3"

jobs:
  run-neo4j-179997:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    services:
      neo4j:
        image: neo4j:5.26-community
        env:
          NEO4J_AUTH: neo4j/password
        ports:
          - 7474:7474
          - 7687:7687

    env:
      NEO4J_HOST: localhost
      NEO4J_PORT: 7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: password
      LEAD_CODE: ${{ github.event.inputs.lead_code || 'BP-L-101' }}
      TOP_K: ${{ github.event.inputs.top_k || '3' }}

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Agents Offline (sin base de datos)
        run: python src/neo4j_179997.py --offline

      - name: Wait For Neo4j
        run: |
          python - <<'PY'
          import time
          from neo4j import GraphDatabase

          for attempt in range(1, 31):
              try:
                  with GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password")) as driver:
                      driver.verify_connectivity()
                  print("Neo4j listo.")
                  break
              except Exception:
                  print(f"Esperando a Neo4j ({attempt}/30)...")
                  time.sleep(2)
          else:
              raise RuntimeError("Neo4j no respondio a tiempo.")
          PY

      - name: Run Neo4j Prospectos y Recomendacion
        run: python src/neo4j_179997.py
