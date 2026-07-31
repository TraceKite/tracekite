# Using the views

Reference for the three views and the controls they share. The
[README](../README.md) covers what Adduce is and how to run it; this is what
to do once it is running.

## Three views, three questions

| | **Repo** | **Service Map** | **Trace** |
|---|---|---|---|
| The question | *What is in these codebases, and where do they touch?* | *What exists, and what talks to what?* | *How does A reach B, and through which hops?* |
| Altitude | code — files, classes, endpoints | services | one journey between two services |
| Layout | force-directed | force-directed cloud | hop-ordered columns |
| Use it to | read a codebase, and see the call sites that cross into another module | find a service, see its callers, spot an unexpected cluster | answer "if I change this endpoint, who breaks?" with a file and line per hop |

**They are a sequence, not alternatives.** Start on the Service Map, select a
service, and choose **Trace from here** — Trace opens with that endpoint
already filled in.

## The header

One row holds everything that applies across the app: the view tabs, an
**Ingest** button, the repository picker, and node search.

Ingest sits behind its button because it is a once-per-repository setup
action. The picker and the search are what you reach for every session.

## Choosing repositories

One picker serves all three views. Search filters the list; the cap on how
many can be selected at once is `MAX_SCOPE_REPOS` in `.env`, default 10.

The cap is a guardrail, not a measure of cost — repository size varies
enormously, and on the demo corpus one repo carries 48 services while five
others total 17. So the picker also shows the live cost of the current
selection ("2 of 10 selected · 51 services · 186 links") and warns as it
approaches the point where the service map truncates.

**Scope applies to all three views**, with one asymmetry worth knowing: in
Trace it limits which services you can *pick*, but paths are still walked
through every repository. Filtering intermediate hops would report "no path"
whenever a real route passes through an unselected repo — a false negative in
the one view whose whole value is trustworthy evidence. Hops outside the scope
are marked in the result rather than hidden.

## Search

Search queries the whole repository; the canvas draws a capped sample of it.
On a large repo those are very different sets — one estate here is 31,000
nodes against a 300-node canvas — so most hits are real but not currently
drawn.

Selecting such a hit opens its details and offers **Show it on the graph**,
which *adds* that node and its neighbourhood to what is already drawn. The
rest of the graph stays; a banner marks the addition and offers a reset. A hit
already on the canvas is centred instead.

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

Switching view clears the highlight, because the two views do not share an
edge vocabulary.

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

## Reading the colours

Colour does two orthogonal jobs, so they never compete:

| Channel | Carries | Why there |
|---|---|---|
| edge colour | the *kind* of relationship — one reserved magenta means "crosses a module" | an edge spans two modules and has no single identity to encode |
| node ring | *which* module the node belongs to | a node does have one identity, and two hues either end of a line make a crossing self-evident |

The node's fill still carries its type, so nothing is displaced. A sidebar
legend names the colours; rings appear only when more than one module is on
screen.
