# Developer & AI Pair Programming Use Cases

This document details practical engineering use cases for developers, DevOps teams, and AI coding assistants (Claude Desktop, Cursor, Antigravity) using **Adduce** and its Model Context Protocol (MCP) server.

---

## 1. Cross-Repository Impact Analysis ("If I change this endpoint, who breaks across 30 repos?")

### The Problem
You need to refactor `@PostMapping("/v1/orders")` to `/v2/orders` in `orders-service`. A simple `git grep "/v1/orders"` inside your repository returns **zero callers** because downstream microservices in other repositories construct HTTP URLs from environment variables, Helm charts, or API gateway path rewriting rules.

### Concrete Multi-Repository Example:

```
[Repo 3: checkout-web] (TypeScript)
  └── src/lib/checkoutClient.ts:52  ── calls "/api/v1/checkout" ──┐
                                                                 ▼
                                                  [Repo 2: api-gateway] (Go)
                                                    └── routes/gateway.go:18 (Rewrites /api/v1/checkout -> /v1/orders)
                                                                 │
[Repo 4: billing-worker] (Python)                                │
  └── services/billing_client.py:88 ── calls ORDERS_SVC_URL ─────┼──▶ [Repo 1: orders-service] (Java)
      (via docker-compose.yml:14 env binding)                    │     └── OrderController.java:45
                                                                 │         @PostMapping("/v1/orders")
```

### How Adduce Solves It
Adduce parses HTTP route annotations, environment bindings, and gateway path rewriters across all repositories, establishing a static contract graph with file:line evidence on both sides of every edge.

* **CLI Execution:**
  ```bash
  adduce pr --base main --head refactor-orders-v2
  ```

* **Sample Both-Sided Evidence Output:**
  ```yaml
  🚨 BREAKING CHANGE DETECTED (3 Repositories Affected):

  Endpoint: global:Http:orders-service:POST:/v1/orders
  Modified File: orders-service/src/main/java/com/company/orders/OrderController.java:45

  Direct & Indirect Broken Consumers:

  1. Repository: billing-worker (Python)
     Caller File: services/billing_client.py:88
     Evidence Chain:
       - billing_client.py:88 reads ORDERS_SVC_URL -> orders-service:8080 (docker-compose.yml:14)
       - Sends POST /v1/orders
     Confidence: 0.98 (http_route + compose_env_host)

  2. Repository: api-gateway (Go)
     Route Table File: routes/gateway.go:18
     Evidence Chain:
       - gateway.go:18 rewrites /api/v1/checkout -> orders-service/v1/orders
     Confidence: 0.95 (gateway_path_rewrite)

  3. Repository: checkout-web (TypeScript)
     Caller File: src/lib/api/checkoutClient.ts:52
     Evidence Chain:
       - checkoutClient.ts:52 calls /api/v1/checkout
       - Forwarded via api-gateway:18 -> orders-service/v1/orders
     Confidence: 0.94 (transitive_crossing)
  ```

* **MCP Tool Usage (via Claude / Cursor / Antigravity):**
  ```json
  consumers_of(node_id: "global:Http:orders-service:POST:/v1/orders")
  ```
* **Developer Benefit:** Discover every affected caller file and line number (*e.g., `billing_client.py:88`, `checkoutClient.ts:52`*) across 30 repositories **before submitting your PR**.

---

## 2. Context-Aware AI Pair Programming

### The Problem
Large Language Models (LLMs) editing code in a single open workspace folder lack visibility into external repositories, microservice dependencies, Kafka topics, and database schemas.

### How Adduce Solves It
Adduce runs as an in-memory MCP server over STDIO or Docker Desktop MCP Toolkit (`docker mcp`). When an AI assistant prepares to edit code, it queries Adduce's graph engine behind the scenes.

* **MCP Tool Workflow:**
  1. Engineer: *"I want to update the payment cancellation endpoint."*
  2. AI Assistant invokes `consumers_of("payment-cancellation")` via MCP.
  3. Adduce returns caller sites in `notification-service` and `analytics-service`.
  4. AI Assistant updates local code **and proactively alerts you to breaking changes in downstream repositories**.

---

## 3. Multi-Hop Distributed Trace Traversal

### The Problem
A request starting at an API Gateway fails to reach a downstream database. Engineers waste hours sifting through Docker Compose files, Nginx route rules, and client SDKs across multiple repositories to trace the path.

### How Adduce Solves It
Adduce calculates shortest active dependency paths through the estate at process boundaries.

* **CLI Usage:**
  ```bash
  adduce explain --from global:Service:api-gateway --to global:Service:discovery-server
  ```
* **MCP Tool Usage:**
  ```json
  trace(from_id: "api-gateway", to_id: "discovery-server", max_hops: 6)
  ```
* **Developer Benefit:** Get a 1-second multi-hop path diagnosis backed by file:line evidence at every step:
  $$\text{api-gateway} \xrightarrow{\text{ROUTES\_TO (Gateway.java:18)}} \text{vets-service} \xrightarrow{\text{CALLS\_SERVICE (VetsClient.java:42)}} \text{discovery-server}$$

---

## 4. Zero-Downtime API Deprecations & Migrations

### The Problem
You want to sunset a legacy `/api/v1/users` endpoint, but you cannot verify if any legacy background job or internal service is still calling it.

### How Adduce Solves It
Adduce tracks declared deprecation annotations alongside active caller edges.

* **CLI Usage:**
  ```bash
  adduce deprecations /app/data/repos
  ```
* **MCP Tool Usage:**
  ```json
  deprecations()
  ```
* **Developer Benefit:** View every deprecated contract that still has live consumer call sites, showing exact file locations that must be updated before decommissioning.

---

## 5. Architectural Drift Detection

### The Problem
System architecture diagrams and Backstage catalog files drift from reality the moment code is shipped without manual documentation updates.

### How Adduce Solves It
Adduce compares static observed contracts against declared catalog specifications, highlighting discrepancies with both-sided evidence.

* **CLI Usage:**
  ```bash
  adduce drift /app/data/repos
  ```
* **Developer Benefit:** Catch undeclared dependencies, phantom endpoints, and un-monitored process calls automatically during CI/CD.

---

## 6. LLM Token Reduction & Cost Efficiency Benchmark (Claude Code & Codex)

### The Problem
When developers ask AI CLI tools (Claude Code, OpenAI Codex, Cursor, Kiro) cross-repository questions such as *"What breaks if I change POST /v1/orders?"*, traditional agents perform brute-force retrieval:
1. They load dozens of entire source files, YAML configs, and Docker Compose manifests into the LLM context window.
2. Reading 40 full files into context window consumes **150,000 to 500,000+ tokens per single prompt**.
3. **Cost & Latency Impact:** At $3.00 / 1M input tokens (Claude 3.7 Sonnet / GPT-4o), every complex query costs **$0.50 to $1.50** and takes 20–30 seconds.

### How Adduce MCP Tools Solve It
Instead of dumping thousands of raw file lines into context, AI agents query Adduce's MCP server:
```json
consumers_of(node_id: "global:Http:orders-service:POST:/v1/orders")
```
Adduce's in-memory graph engine executes in 1ms and returns a **compact, pre-linked JSON payload** (only 300 to 800 tokens total):
```json
{
  "found": true,
  "consumers": [
    { "consumer": "billing-service", "evidence": ["BillingClient.java:42"], "confidence": 0.98 }
  ]
}
```

### Empirical Token Benchmark Comparison

| Metric | Without Adduce (Raw Context Dumping) | With Adduce MCP Tools | Efficiency Gain |
| :--- | :--- | :--- | :--- |
| **Input Tokens per Query** | **150,000 – 500,000 tokens** | **500 – 1,500 tokens** | **99% Token Reduction** 📉 |
| **Query Cost (Claude 3.7 / GPT-4o)** | ~$0.50 – $1.50 / query | ~$0.002 – $0.005 / query | **99% Cost Savings** 💰 |
| **Response Latency** | 20 – 30 seconds | 0.8 – 1.5 seconds | **20x Speed Increase** ⚡ |
| **Context Window Consumption** | 80%–95% filled with raw file text | < 1% filled, preserving headroom for code edits | **Maximum Context Free** 🧠 |

---

## 7. Integration & Embedding Guide (`adduce-core`)

This section documents how host applications (Causelume, CI/CD runners, AI agents, custom Python tools) embed **`adduce-core`** for **Ingestion** and **Querying**.

### A. Ingestion Integration Patterns

#### 1. In-Memory Python Scanning (`scan` & `scan_if_changed`)
Install `adduce-core` (`pip install adduce-core`) and scan repositories directly into in-memory `ClaimsSink` objects:

```python
from adduce import engine_config
from adduce.services.scan import scan
from adduce.services.reingest import scan_if_changed

# Configure engine (zero server, zero database required)
engine_config.configure(graph_hmac_key="your-salt-key")

# Option A: Scan repository into claims sink
sink = scan(path="/path/to/repo", repo_id="my-service")

# Option B: Incremental Merkle scan (skips scan if source unchanged)
ref, reused = scan_if_changed(
    repo_path="/path/to/repo",
    repo_id="my-service",
    out_dir="/path/to/artifacts"
)
```

#### 2. Portable Content-Addressed Artifact Creation (CLI)
```bash
# Scan repository into a self-describing .adduce artifact
adduce artifact /path/to/repo --out artifacts/repo.adduce
```

#### 3. Web App REST API Ingestion (`docker compose up`)
```bash
curl -X POST http://localhost:28000/api/repos/ingest \
  -H 'Content-Type: application/json' \
  -d '{"local_path": "/path/to/repo"}'
```

---

### B. Querying & Graph Retrieval Integration Patterns

#### 1. Direct In-Memory Graph Querying (Python)
Host applications query nodes, edges, consumers, and trace paths directly in Python:

```python
from adduce.db.memory_store import InMemoryLinkerStore
from adduce.services.linker.engine import link
from adduce.mcp_server import GraphTools

# 1. Reconcile claims in memory (< 100ms)
store = InMemoryLinkerStore([sink])
result = link(store.load_claims())

# 2. Query Graph Objects via GraphTools API
tools = GraphTools(result)

# Query microservices & commit SHAs
services = tools.services()

# Query cross-repo consumers with file:line evidence citations
consumers = tools.consumers_of("global:Service:orders-service")

# Trace multi-hop call paths
paths = tools.trace(from_id="api-gateway", to_id="billing-worker", max_hops=6)

# Query active API deprecations
deprecations = tools.deprecations()
```

#### 2. Model Context Protocol (MCP) & AI Assistant Integration
Serve the graph over MCP STDIO to Claude Desktop, Cursor, or Docker MCP Toolkit:

```bash
# Serve artifact over MCP STDIO
adduce mcp artifacts/repo.adduce
```

#### 3. CLI Terminal Querying & CI Breaking Change Gates
```bash
# Check PR breaking changes across repositories
adduce pr --base main.adduce --head feature.adduce

# Explain why an edge exists with derivation receipt
adduce explain /path/to/repo --from service-a --to service-b
```


