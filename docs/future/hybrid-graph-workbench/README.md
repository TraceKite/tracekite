# Hybrid Graph Workbench — review template

This is the isolated design template that was approved before implementation.
Reviewing it does not alter the running TraceKite application; its approved light,
grouped direction was applied separately on 2026-08-30.

## Design sources

| Source | Retained |
|---|---|
| Current application | Header, Repo/Service Map/Trace structure, view modes, search, inspector and real graph vocabulary |
| Claude Design | Explicit Overview/Focus states, restrained hierarchy, evidence-oriented inspector and mineral palette |
| Google Nano Banana | Strong repository grouping, compact graph controls and spatial 3D composition |

The rejected dark graphite canvas is not used. This version uses a warm light
canvas with graphite text, neutral structure, forest modules, rust selection
and ochre manifests/dependencies.

## What to review

Open [hybrid-graph-workbench.html](hybrid-graph-workbench.html) and check four
states:

1. 2D Overview — nine module groups instead of hundreds of equal-weight nodes.
2. 2D Focus — App.tsx plus exact one-hop relationships.
3. 3D Overview — module groups only, with depth tied to repository/module
   separation.
4. 3D Focus — a bounded selected neighborhood, not the whole estate.

Use the 2D/3D and Overview/Focus controls in the template.

Static review exports:

- [2D Overview](mock-2d-overview.jpg)
- [2D Focus](mock-2d-focus.jpg)
- [3D Overview](mock-3d-overview.jpg)
- [3D Focus](mock-3d-focus.jpg)

Questions for approval:

- Is the light mineral graph surface comfortable and sufficiently clear?
- Should Overview begin with repository/module groups rather than every node?
- Is Focus the right place to reveal exact node labels and direction?
- Does the bounded 3D view explain structure without becoming decorative?
- Is the shell close enough to the current application?

## Local preview

From the repository root:

```bash
python -m http.server 8000 --directory docs/future/hybrid-graph-workbench
```

Open `http://localhost:8000/hybrid-graph-workbench.html`.
