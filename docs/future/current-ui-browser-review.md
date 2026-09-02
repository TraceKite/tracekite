# Pre-redesign Adduce UI browser review

> **Historical baseline.** This document records the UI before the approved
> hybrid redesign was applied. Its problems are not a description of the
> current runtime. See the current
> [interaction contract and QA matrix](navigation-and-feature-qa-2026-08-30.md).

Reviewed on 2026-08-30 at `http://localhost:28080/` before generating either
redesign package and before applying the hybrid implementation.

## What was exercised

- The Repo workspace in 2D and 3D.
- Repository scope with `adduce-labs/adduce` and `sfbayman/lanovyx` selected.
- A 310-node, 346-edge multi-repository canvas.
- Search for `frontend`, selection of `frontend/src/App.tsx`, and the capped
  sample notice with the Show in graph action.
- Service Map with 14 visible services out of 131 and 146 visible links out of
  337 at 60% minimum confidence.
- Distributed Trace from `adduce/frontend-external` to `adduce/backend`, which
  returned two paths at 96% confidence.

## What already works and should remain recognizable

- A compact application shell with Repo, Service Map, and Trace as distinct
  workspaces.
- A mode-specific left rail for view/filter controls.
- A graph-first center canvas and a contextual right inspector.
- Repository scope, search, Ingest, and a direct 2D/3D switch.
- Useful search behavior that can find a node outside the currently rendered
  sample and explain why it is not visible.
- Service and trace controls that expose confidence, hop, and path limits.

## Problems observed in the running UI

1. **Scope continuity is unreliable.** After selecting two repositories, the
   Repo header could continue to display a single repository while the canvas
   and statistics reflected the two-repository scope.
2. **Dense graphs lack a deliberate information hierarchy.** Hundreds of
   edges compete at similar visual weight. Important hubs, repository
   boundaries, and cross-repository links are hard to distinguish quickly.
3. **3D is visually interesting but difficult to read.** Labels overlap and
   depth does not yet produce a clearer investigation path than 2D.
4. **Selection context can become stale.** An inspector from a previous graph
   or edge can remain visible after changing workspace, and one Show in graph
   interaction changed the inspected subject unexpectedly.
5. **Service Map contrast is too weak.** In the reviewed state, dark labels
   and long off-screen edges made the topology difficult to read against the
   black canvas.
6. **Trace results are not visually legible enough.** The successful result
   contained useful path data, but the canvas did not clearly communicate the
   direct route, alternatives, or their evidence.
7. **Controls consume attention without establishing priority.** View modes,
   legends, graph controls, and statistics all compete in the left rail.

## Redesign behavior for hundreds of edges

The graph should have three explicit reading states:

| State | Purpose | Rendering rule |
|---|---|---|
| Overview | Understand estate shape | Cluster by repository/module, label only stable hubs, aggregate low-value parallel edges |
| Focus | Investigate one node or service | Keep one-hop neighbors crisp, dim unrelated context, pin the inspector |
| Isolate | Explain a path or impact chain | Render only ranked paths and required evidence; keep the broader graph as faint orientation context |

Additional rules:

- Apply a label budget based on zoom and importance; never render every label.
- Use repository hulls and quiet whitespace to make scope visible without a
  legend lookup.
- Reserve bright edge treatments for selected, cross-repository, or traced
  relationships. Background edges remain thin and subdued.
- Keep 3D bounded to the selected neighborhood or current trace. Atlas, sphere,
  and layer arrangements must preserve stable node identity and selection.
- Make sampling, hidden-edge counts, and confidence filtering visible near the
  canvas, not only in a settings panel.
- Treat the inspector as part of the investigation state: selected entity,
  inbound/outbound relationships, confidence, repository, and provenance.
- Give Trace a left-to-right reading order with ranked alternatives and
  `file:line` evidence adjacent to the chosen path.

## Visual system

The redesign deliberately avoids blue/purple gradients, glowing blobs, glass
cards, oversized rounded panels, and decorative analytics. It uses IBM Plex
Sans and IBM Plex Mono with a restrained palette:

| Role | Value |
|---|---|
| Graphite canvas | `#20241F` |
| Mineral surface | `#F4F1E9` |
| Bone surface | `#EFEBE1` |
| Smoke text | `#6B6F65` |
| Forest action/selection | `#315B47` |
| Rust cross-scope/accent | `#A45138` |
| Ochre warning/secondary | `#9B7A31` |

Color is never the only carrier of node type, confidence, or selection.
