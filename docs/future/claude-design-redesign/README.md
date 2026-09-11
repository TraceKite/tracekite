# Claude Design — Graph Investigation Workspace

> **Design reference.** The approved hybrid has been implemented. This package
> preserves the Claude design source; current behavior is documented in the
> [runtime QA matrix](../navigation-and-feature-qa-2026-08-30.md).

This is the recommended implementation direction. Claude Design generated the
editable source after the current Evigraph application had been reviewed in the
browser. The layout preserves the real shell and turns Repo, Service Map, and
Trace into one continuous investigation workflow.

Claude Design wrote all five screens before its session quota paused the final
chat response. The exported source was rendered locally and every screen below
was visually verified from that source.

[Open the Claude Design project](https://claude.ai/design/p/c0b40f89-5e1a-4f26-a97c-084e0ec2d535?file=Evigraph+-+Graph+Investigation+Workspace.dc.html)

## Assets

| File | Screen |
|---|---|
| [mock-repo-2d-overview.png](mock-repo-2d-overview.png) | Multi-repository 2D overview with repo hulls, graph counts, scope breakdown, and an empty inspector state |
| [mock-repo-search-inspector.png](mock-repo-search-inspector.png) | Search result outside the capped sample, focused App.tsx neighborhood, and relationship inspector |
| [mock-repo-3d-knowledge-atlas.png](mock-repo-3d-knowledge-atlas.png) | Bounded 3D atlas with stable repository groups, focus controls, neighbor context, and selected-edge details |
| [mock-service-map.png](mock-service-map.png) | Directional service topology with relationship counts and a relevant service inspector |
| [mock-distributed-trace.png](mock-distributed-trace.png) | Ranked direct and alternate paths with confidence and `file:line` evidence |
| [evigraph-graph-investigation.dc.html](evigraph-graph-investigation.dc.html) | Editable five-screen source artifact |
| [support.js](support.js) | Local runtime used by the source artifact |
| [design-tokens.css](design-tokens.css) | Portable color, type, spacing, and geometry tokens |

## Local preview

From the repository root:

```bash
python -m http.server 8000 --directory docs/future/claude-design-redesign
```

Then open
`http://localhost:8000/evigraph-graph-investigation.dc.html`.

## Why this direction is stronger

- The five screens form one product flow rather than unrelated hero images.
- The 2D view makes repository boundaries and sampling explicit.
- Search becomes an investigation transition: find, disclose the capped state,
  focus the node, then inspect its neighborhood.
- The 3D view is a bounded knowledge atlas with the same entity identity and
  inspector contract as 2D.
- Service Map clears unrelated node state and uses a directional topology.
- Trace ranks alternatives and puts source evidence next to the path it proves.

The mock values are design content, not a new graph-data source. Production
implementation must use the existing API/store contracts and retain real
provenance.
