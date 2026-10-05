<picture>
  <source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/tracekite-horizontal-reverse.svg">
  <img alt="TraceKite" src="frontend/public/brand/tracekite-horizontal.svg" width="300">
</picture>

**Find connections across repositories, with source evidence you can check.**

TraceKite reads code and configuration to connect services, HTTP endpoints,
packages, message topics, and datasets. Use it to investigate which indexed
consumers could be affected by a change, then open the cited files to verify why.
It analyzes source; it does not run your applications or require an LLM.

For example, an HTTP call in one repository, a URL in Docker Compose, and a
route in another repository can establish this connection:

```text
orders-service ──CALLS_SERVICE──▶ billing-service
                  evidence: src/billing_client.py:14

Python caller ──INVOKES──▶ GET /v1/invoices/{} ◀──EXPOSES── Go handler
```

The [included demo](corpus/README.md) contains both services. A missing edge means
TraceKite did not establish a connection in the supplied inputs; it does not
prove that changing or deleting the code is safe.

## Choose your starting point

| I want to… | Start here | What it needs |
|---|---|---|
| Explore repositories in a browser | [Run the app](docs/quickstart.md) | Docker Compose, Git, OpenSSL |
| Scan code or check a branch in CI | [Use the CLI](docs/cli.md) | Python 3.13+; no server |
| Give an agent graph tools | [Connect MCP](docs/plugins-and-mcp-guide.md) | CLI and an MCP client; no server |
| Embed queries in Python | [Use the library](docs/library.md) | `pip install tracekite-core` |
| Understand or extend the engine | [Architecture](docs/design/architecture.md) → [Contributing](CONTRIBUTING.md) | Source checkout |

The Docker app stores its graph in Neo4j. The CLI, library, and MCP server
scan local directories or read portable artifacts independently; **they do not
query the Docker app's database**.

## Try the CLI on a small example

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python
3.13 or later. Run these commands in a terminal:

```bash
uv tool install tracekite-core
git clone https://github.com/TraceKite/tracekite.git
cd tracekite
tracekite link corpus/orders-service corpus/billing-service
```

The JSON output should include `CALLS_SERVICE` from
`global:Service:orders-service` to `global:Service:billing-service`, evidence,
and resolver counters. Nothing from the demo is executed.

For your own repositories, replace the two paths. Use a private, stable
`GRAPH_HMAC_KEY` when analyzing sensitive configuration; the
[CLI guide](docs/cli.md#before-scanning-your-own-code) explains the setup.

## Run the browser app

From the checkout above:

```bash
./scripts/setup.sh
docker compose up -d --build
```

Open <http://localhost:28080>. Choose **Ingest**, enter a Git repository URL,
and wait for ingestion and the automatic link rebuild. Then select the
repositories you want to explore.

- **Repo:** inspect files, endpoints, dependencies, and local code in 2D or 3D.
- **Service Map:** see resolved services and their supported connections.
- **Trace:** inspect static paths and source evidence between two services.

Follow the [app walkthrough](docs/quickstart.md) for a public two-repository
example, expected results, updating code, and troubleshooting. Existing stacks
should reuse their project, ports, and volumes; see [configuration](docs/configuration.md).

## Embed it in Python

In your Python environment, install the library and supply a private key:

```bash
pip install tracekite-core
export GRAPH_HMAC_KEY="$(openssl rand -hex 32)"
```

From the checkout root:

```python
import os
from tracekite.facade import TraceKite

tk = TraceKite(["./corpus/orders-service", "./corpus/billing-service"],
               graph_hmac_key=os.environ["GRAPH_HMAC_KEY"])
answer = tk.consumers_of("global:Service:billing-service")
print(answer.model_dump(mode="json"))
```

The [library guide](docs/library.md) covers setup, all nine query methods,
artifacts, storage adapters, and interpreting incomplete answers.

## What can I use it for?

| Task | TraceKite helps you find |
|---|---|
| Review an API change | Indexed callers and the source locations to inspect |
| Onboard to a system | Code structure, resolved services, and paths between them |
| Upgrade a shared package | Publishers, consumers, and recorded version differences |
| Investigate an event flow | Declared topics, producers, consumers, and supported fan-out |
| Review a pull request | Connections lost between supplied base and head artifacts |
| Build an agent integration | Node lookup, search, neighbors, subgraphs, and dependency impact |

See [use cases](docs/use-cases.md) for the steps and the limits of each answer.
[Features and coverage](docs/features.md) shows which capabilities are available
in the UI, CLI, Python library, MCP, and HTTP API.

## Read next

- [Documentation index](docs/README.md): short guides organized by task.
- [Reading graph answers](docs/answers.md): confidence, evidence, empty results, and scope.
- [Coverage limits](docs/design/coverage-gaps.md): unsupported patterns and known differences between surfaces.
- [Changelog](CHANGELOG.md) and [releases](https://github.com/TraceKite/tracekite/releases).
- [Contributing](CONTRIBUTING.md), [support](SUPPORT.md), and [security](SECURITY.md).

Apache 2.0. See [LICENSE](LICENSE).
