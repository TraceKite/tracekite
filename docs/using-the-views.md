# Use the browser views

[Docs](README.md) · Prerequisite: [App quickstart](quickstart.md)

## Three tabs, one repository scope

| Tab | Question | What you see |
|---|---|---|
| **Repo** | What is in these repositories? | Source structure, nodes, local edges, supported call/contract bridges |
| **Service Map** | Which services are connected? | Resolved services and service/topic relationships |
| **Trace** | How can service A reach service B? | Ranked static paths with evidence; optional HTTP crossings |

Trace is source-based dependency tracing, not recorded distributed telemetry.
Repo and Service Map have different node families, so their totals need not
match. Their repository selection should match.

Open the header's repository picker, change the selection, then click **Apply
scope**. **Cancel** discards edits; Escape closes the picker. The default scope
cap is 20 repos; **All repositories** is disabled when the estate exceeds it.
The picker displays source-node counts in Repo and service counts in map/trace
mode, with service/link cost when map data is loaded.

In Trace, scope restricts the endpoint picker. A path may still pass through
an unselected repo; outside-scope hops remain visible.

## Repo view modes

| Mode | Emphasizes |
|---|---|
| **Overview** | Source structure, grouped by repository/module |
| **Architecture** | Endpoints, infrastructure, dependencies, config, code containers |
| **Code** | Files, classes, interfaces, methods, functions, local calls |
| **API** | Endpoints and their handlers/source containers |
| **Dependencies** | Manifests, local dependency records, dependency edges |
| **Impact** | Up to two **outgoing** hops from the selected node in its local graph |

Repo Impact requires a selected node. It is not MCP's transitive “who depends
on this?” query and is not a complete cross-repo blast radius.

Broad modes initially show module groups. Each group summarizes the returned
source nodes; it is not a new database node. The context bar distinguishes
loaded nodes, filtered/eligible nodes, displayed nodes, and visible edges.
Search can reach nodes outside the loaded sample.

## Selecting versus opening

| Action | Result |
|---|---|
| Click a node/group | Read properties or a group summary in the drawer |
| Double-click, or `o` with a node selected | Open a module's members or a node's one-hop neighborhood |
| Select a search result | Fetch its bounded neighborhood and open the inspector |
| Click an inspector relationship | Inspect the related node; load its neighborhood if it is outside the sample |
| Drawer **X** | Close the inspector and keep the canvas level |
| **Back** or Escape | Unwind a path/selection, opened node, or module toward the grouped entry |
| **Return to Overview** | Clear the focused investigation and reload Overview |

The default exact display cap is 80 nodes. A long list or a large module can
be truncated; use search to reach an omitted node. Navigation has overview,
module, and focused-neighborhood levels; it is not an unlimited history of
every node visited. Opening another node replaces the current node focus.

2D/3D share scope, filters, and graph level. Switching dimensions preserves
module/focus context; the local 3D path is cleared.

## Search, filters, and controls

Type at least two characters. Search queries the scoped repositories and shows
repo/path with each result. Each repo ranks exact spelling/case first; the
combined dropdown shows up to 50 rows. An empty result is explicit.
**Clear search** clears the text/results; **Return to Overview** leaves the
focused graph.

- **Node Types:** hide/show source node families present in the loaded dataset.
- **Edge Types / Relations shown:** click a row to highlight it; use the eye
  icon to hide it. Several relationship types can be highlighted together.
- **Lockfile leaves hidden:** suppress indirect dependency clutter while
  retaining direct dependency information.
- **Show connections only:** in multi-repo mode, focus the view on supported
  HTTP contract bridges instead of each repo's internals.
- **2D controls:** Reset, Fit, Rotate, Settle/Re-layout, Labels, Particles,
  Fullscreen. Escape or Exit fullscreen restores the normal layout.
- **3D controls:** Less noise, Labels, zoom in/out/100%, Reset. Focus the graph
  for keyboard shortcuts; `L` toggles labels. Shift-click/Shift-Enter another
  node requests a directed local path through the loaded graph.

In 0.2.0, **Show connections only** can hide call sites connected only by
`UI_CALLS`; leave it off to inspect those frontend bridges.

A 3D local path is not a distributed Trace. A hidden type can remain listed so
you can turn it back on. Repo filter counts describe the loaded dataset;
Service Map relation counts describe the projected visible links.

Each sidebar can collapse to a labelled rail. It may collapse automatically on
narrow screens to leave space for the graph and inspector. The rail reopens it.

## Inspect evidence

A node drawer shows its ID, type, path/language where available, stored
properties, and incoming/outgoing relationships. **Copy path** copies the path.
A group drawer shows a computed summary rather than source-node properties.

A relationship drawer shows its type, confidence/range, detection signals,
available routing details, and citations. Open the cited source revision to
check the claim. Node fill identifies type; rings identify module when several
modules are visible; edge colors distinguish relationships and crossings.

## Service Map

Use **Find a service on the map** or select a service on the canvas. Its panel
shows Called by, Calls, repository attribution, and **Trace from/to here**.
Selecting a relationship opens the evidence drawer. Services with no displayed
links remain in the unconnected shelf.

The top bar counts displayed nodes/links. The sidebar counts services and links
using the same scope/filter projection; displayed nodes can also include topics.
Minimum confidence and relation visibility change the counts.

Ingestion and refresh queue linking automatically. The map shows **Rebuilding
links**, prevents duplicate rebuild clicks, and refreshes after an observed run
completes. **Links are stale** means ingested data is newer than the successful
link state. If rebuilding fails, inspect the status/error using the
[HTTP API](api.md#jobs-and-freshness) before retrying.

“No services in this scope” can be valid for a library or unsupported service
identity. A populated Repo graph alone does not imply a populated Service Map.

## Trace

Choose different origin/destination services, then click **Trace Paths**.

| Setting | Choices |
|---|---|
| Altitude | Service or Code (Crossings) |
| Minimum confidence | 0.60–1.00 |
| Maximum hops | 1–8 |
| Maximum paths | 1–5 |

Changing a constraint clears old results. Click **Inspect source → target** on
a hop to open its evidence drawer. Code altitude adds supported HTTP crossings;
it does not reconstruct every method call in the application.

A no-path result means no path matched the graph and constraints. Try a broader
scope for endpoint discovery, inspect coverage, or adjust constraints; do not
assume that runtime communication is impossible.

Manage source through **Ingest**, **Refresh repository**, and **Delete
repository** as described in the [quickstart](quickstart.md#4-keep-it-current).
