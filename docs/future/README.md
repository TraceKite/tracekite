# Evigraph front-end redesign studies

These two packages replace the earlier concept-first drafts. Both were created
after reviewing the running application at `http://localhost:28080/`, including
multi-repository Repo 2D and 3D, search and selection, Service Map, and a
successful distributed Trace.

The [browser review](current-ui-browser-review.md) is the historical baseline
that motivated both directions, and the
[QA matrix](navigation-and-feature-qa-2026-08-30.md) records the acceptance
pass that followed. Both are dated records; current behaviour is documented in
[Using the views](../using-the-views.md).

The implemented hybrid decision and research are captured in the
[five-lens graph UX review](graph-ux-five-lens-review.md).

The applied interaction contract and browser acceptance matrix are in
[navigation-and-feature-qa-2026-08-30.md](navigation-and-feature-qa-2026-08-30.md).

The current review-first prototype is the
[Hybrid Graph Workbench](hybrid-graph-workbench/README.md). It remains the
visual acceptance reference for the approved light, grouped implementation.

| Package | Created with | Deliverables | Recommended use |
|---|---|---|---|
| [Claude Design redesign](claude-design-redesign/README.md) | Claude Design | Editable `.dc.html`, local runtime, five complete mock screens | Primary implementation reference |
| [Google Nano Banana redesign](google-nano-banana-redesign/README.md) | Google Stitch Redesign with Nano Banana | Four wide mock screens | Alternate visual direction and graph-density reference |

## Implemented decision

The applied hybrid uses the Claude package's investigation hierarchy and the
Google direction's compact grouping/spatial treatment. These mocks explain the
decision; the running frontend and QA matrix are now the source of truth for
behavior, counts and navigation.

## Shared design contract

- Preserve the current top-level information architecture: Repo, Service Map,
  Trace, 3D/2D, repository scope, search, and Ingest.
- Keep the graph as the primary workspace. Metrics support the graph; they do
  not replace it with a dashboard.
- Make sampling explicit. A capped canvas must never look like the complete
  graph.
- Scale through overview, focus, and isolate states rather than drawing every
  edge at equal weight.
- Preserve selection when moving between 2D, 3D, Service Map, and Trace; clear
  an inspector when its subject is no longer relevant.
- Give evidence and `file:line` provenance first-class space in inspectors and
  trace results.
- Use graphite, bone, smoke, forest, rust, and ochre. Blue and purple are not
  part of either direction.

The Google and Claude packages remain design assets. The approved hybrid has
now been applied to the local production frontend; the QA document above is
the current implementation evidence.
