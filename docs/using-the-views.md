# Using the views

Reference for the three views and the controls they share. The
[README](../README.md) covers what Adduce is and how to run it; this is what
to do once it is running.

## Three views, three questions

| | **Repo** | **Service Map** | **Trace** |
|---|---|---|---|
| The question | *What is in these codebases, and where do they touch?* | *What exists, and what talks to what?* | *How does A reach B, and through which hops?* |
| Altitude | code — files, classes, endpoints | services | one journey between two services |
| Layout | grouped 2D/3D with bounded exact detail | force-directed service topology | hop-ordered columns |
| Use it to | read a codebase, and see the call sites that cross into another module | find a service, see its callers, spot an unexpected cluster | answer "if I change this endpoint, who breaks?" with a file and line per hop |

**They are a sequence, not alternatives.** Start on the Service Map, select a
service, and choose **Trace from here** — Trace opens with that endpoint
already filled in.

## The header

One row holds the workspace tabs, **Ingest**, and the repository picker. Repo
also exposes node search and the 2D/3D projection switch; those controls are
hidden in Service Map and Trace because both have their own fixed layouts.

Ingest sits behind its button because it is a once-per-repository setup
action. The picker and the search are what you reach for every session.

## Choosing repositories

One picker serves all three views. Selection is staged: edit the checkboxes,
then choose **Apply scope** to cause one navigation and one data load. Search
filters the list; the cap is `MAX_SCOPE_REPOS` in `.env`, default 10. **All
repositories** is disabled when the estate is larger than that cap.

The cap is a guardrail, not a measure of cost — repository size varies
enormously, and on the demo corpus one repo carries 48 services while five
others total 17. When Service Map data is loaded, the cross-view picker also
shows the live service/link cost and warns as it approaches the map's edge
ceiling.

**Scope applies to all three views**, with one asymmetry worth knowing: in
Trace it limits which services you can *pick*, but paths are still walked
through every repository. Filtering intermediate hops would report "no path"
whenever a real route passes through an unselected repo — a false negative in
the one view whose whole value is trustworthy evidence. Hops outside the scope
are marked in the result rather than hidden.

## Search

Search queries every repository in scope while the canvas draws a capped
sample. Results identify their repository and path; the dropdown visibly caps
itself at 50 rows.

Selecting a result navigates directly to that node's exact bounded local
neighborhood and opens its inspector. It does not merge the result into an
unrelated sampled graph. **Return to Overview**, Back, or Escape clears the
search investigation and reloads grouped Overview.

## Repo View Modes and graph levels

View Mode chooses the backend dataset; it does not disable the density rules:

| Mode | Emphasizes |
|---|---|
| **Overview** | repository, folder, file, class, endpoint and dependency structure |
| **Architecture** | endpoints, infrastructure, dependencies, config and major code containers |
| **Code** | files, classes, interfaces, methods, functions and calls |
| **API** | endpoints and the files/functions/methods that expose them |
| **Dependencies** | manifests, dependencies and `DEPENDS_ON` relationships |
| **Impact** | the selected node's exact two-hop neighborhood; disabled until a node is selected |

Every broad mode opens as repository/module groups. Select a group for bounded
exact detail, then select or search a node for Focus. `GRAPH_DETAIL_NODE_LIMIT`
(default 80) caps Module, Focus and Impact display without inventing edges;
search still reaches nodes outside that display bound.

The context bar distinguishes groups, filter-eligible nodes, loaded nodes,
displayed nodes and exact visible edges. For example, Dependencies may say
`4 groups · 29 eligible of 320 loaded` while **Lockfile leaves hidden** is on.

2D and 3D share scope, filters, selected node and navigation level. Switching
dimensions preserves Module/Focus; a local 3D path is cleared because 2D does
not render it. Back and Escape unwind Path → Focus → Module → grouped entry.

### Canvas controls

- **2D:** Reset camera, Fit, Rotate, Settle/Re-layout, Labels, directional
  Particles and Fullscreen. Settling forces never disables navigation.
- **3D:** Less noise, Labels, zoom in/out/100% and camera Reset. `L` toggles
  labels after the graph receives focus. Click a node for Focus; Shift+click or
  Shift+Enter another node for a directed local path through edges already on
  the sampled canvas.

3D's local path is orientation, not a ranked distributed Trace. The path bar
names it accordingly.

## Highlighting versus filtering

Two different operations on the same list.

**Filtering removes.** To see where one relationship lives you delete every
other one — and lose the structure that made it meaningful.

**Highlighting emphasises.** Matching edges keep full strength and thicken;
everything else recedes to a few percent but stays on screen. You see the
needle *and* the haystack.

In **Edge types** (Repo) and **Relations shown** (Service Map), clicking a row
highlights it and the eye icon hides it. They compose: filtering decides what
exists, highlighting decides what stands out. Several types can be lit at
once, and each row shows how many edges of that type are present — often the
fastest way to notice a relationship you expected has a count of zero.

Switching workspace clears the highlight, because Repo and Service Map do not
share an edge vocabulary.

## Where modules connect

**The boundary is the module, not the repository.** A repository is how code
is *stored*; a module is what owns behaviour. A monorepo holds many services,
so treating the repo as the boundary would hide every crossing inside it.

A module is the directory owning a unit of behaviour: the segment beneath
`projects/`, `services/`, `apps/`, `packages/` and similar container
directories, or the top-level directory in a single-service repository.
Crossings therefore show up whether the two sides live in one repository or
two.

A repository's own graph is *intra-repo* by construction — files contain
classes, classes declare methods. Nothing in it crosses a boundary, so drawing
two repositories together would otherwise give you two disconnected islands.

What crosses is a **rendezvous**: a call site `INVOKES` a contract that
another module's endpoint `EXPOSES`, and the contract is the meeting point.

```
foyer/registry_projection_cache.py ──INVOKES──▶ GET /v1/callers ◀──EXPOSES── capability-registry/routes.go
```

The Repo view fetches those bridges and draws the contracts as connectors.
**Show connections only** hides each codebase's internals and leaves just the
joining tissue.

If a selection has no bridges, the view says so rather than drawing silent
islands. That is not a failure — two modules that never call each other
genuinely have nothing between them.

Bridges come from the linker, so they appear once a link run completes. You do
not have to trigger one — every ingest and refresh queues a relink
automatically, and a burst of ingests coalesces into a single run. A manual
rebuild exists for when you have changed linker configuration rather than
code.

## Service Map

The top status reports nodes and links actually displayed; the sidebar reports
services and relation candidates in scope. Unconnected services are kept in a
stable shelf and counted instead of stretching the connected topology.

Use minimum confidence and the five **Relations shown** rows to change the
map. Row click highlights; the eye button hides. **Find a service** is the
keyboard-accessible route to every displayed service. A focused service shows
Called by, Calls, repository attribution and **Trace from/to here**. Selecting
a relationship opens confidence, detection signals and cited `file:line`
evidence.

The transient **Arranging service map…** state hides unstable force positions
until the map has been framed.

## Trace

Choose different origin and destination services, then set:

- **Altitude:** Service or Code (Crossings);
- minimum confidence: 0.60–1.00;
- maximum hops: 1–8;
- maximum ranked paths: 1–5.

Changing an endpoint or constraint clears prior results and any stale edge
drawer. Success renders ranked left-to-right paths; no-match is an explicit
state, not a blank canvas. Each path lists **Inspect source → target**, which
opens the same evidence drawer without requiring a precision click on a line.

## Reading the colours

Colour does two orthogonal jobs, so they never compete:

| Channel | Carries | Why there |
|---|---|---|
| edge colour | the *kind* of relationship — reserved rust means "crosses a module" | an edge spans two modules and has no single identity to encode |
| node ring | *which* module the node belongs to | a node does have one identity, and two hues either end of a line make a crossing self-evident |

The node's fill still carries its type, so nothing is displaced. A sidebar
legend names the colours; rings appear only when more than one module is on
screen.
