# Evigraph graph UX: five-lens review and hybrid direction

Reviewed and implemented on 2026-08-30 against the running application at
`http://localhost:28080/`.

## Review status

The dark graphite implementation experiment was rejected during visual review:
it remained too dense, dark and difficult to understand. It is not an approved
design direction. The replacement review artifact is the isolated
[Hybrid Graph Workbench](hybrid-graph-workbench/README.md), which uses a light
mineral canvas and grouped Overview. That hybrid was approved and applied to
the local application on 2026-08-30, then browser-verified in 2D Overview,
module detail, one-hop Focus, 3D Overview and 3D Focus.

The tables below compare the **pre-redesign baseline** with the two design
packages. Current runtime status is recorded in the
[interaction QA matrix](navigation-and-feature-qa-2026-08-30.md).

This review compares three sources:

1. the existing working application;
2. the [Claude Design investigation workspace](claude-design-redesign/README.md);
3. the [Google Stitch / Nano Banana screens](google-nano-banana-redesign/README.md).

It evaluates them through five engineering lenses: graph visualization,
frontend performance, developer-tool product design, accessibility/design
systems, and graph trust/reliability.

## Executive decision

The target is a hybrid, not a direct copy of any template.

- Keep the existing renderer, API contracts, search, selection, inspectors and
  real graph data.
- Adopt Claude's information hierarchy, explicit overview/focus/path states,
  evidence-oriented inspector structure and restrained mineral palette.
- Borrow Google's strong cluster contrast, compact node marks and spatial 3D
  composition without adopting its dark canvas.
- Reject the existing blue/purple visual system, equal-weight edge hairball,
  stale cross-view inspector state and motion-first 3D treatment.
- Reject generated mock data and code as a source of graph truth. Layout is a
  reference; production labels, counts, paths and evidence come only from the
  running contracts.

2D is the primary reasoning surface. 3D is a narrower investigation mode for
repository/module topology and a selected neighborhood. Trace remains the
only product surface allowed to claim a ranked service path.

## Comparative review

| Surface | Existing application | Claude Design | Google Nano Banana | Hybrid decision |
|---|---|---|---|---|
| Product hierarchy | Real but crowded | Strongest hierarchy | Visually strong, less systematic | Claude structure |
| Dense graph composition | Real data, frequent hairball | Clear regions but sometimes too faint | Strong contrast and convincing density | Google contrast with Claude hierarchy |
| Search and focus | Functional, rich real inspector | Best focus/context composition | Inspector is present but shallow | Existing behavior with Claude focus state |
| 3D | Real renderer, unstable and decorative controls | Semantically clearer but visually flat | Strongest spatial composition | Existing engine with Claude semantics and Google contrast |
| Service Map | Low-contrast and retained stale Repo inspector | Clear directional topology | Clean but oversimplified | Claude direction |
| Trace | Real contract but weak visual result | Best ranked-path/evidence layout | Strong path composition, generated evidence unsafe | Claude layout backed only by real Trace data |
| Visual system | Blue, indigo and purple | Mineral, graphite, forest, rust, ochre | Graphite, forest, rust and ochre | Light mineral canvas with forest, rust and ochre |
| Production readiness | Functional | Static design source | Raster design reference | Existing implementation evolved in place |

### Existing application

What should stay:

- It renders real API data and actual edge direction.
- Search finds entities outside the capped canvas sample.
- Selecting a node can expose substantial inbound/outbound relationship data.
- 2D and 3D already share scope, filters and selected entities.
- Canvas/WebGL rendering is appropriate for the current hundreds-of-elements
  workload.

What must change:

- The live single-repository overview contained 485 loaded nodes and 371
  edges. Labels competed with one another and the blue/purple encoding did not
  establish task priority.
- The reproduced two-repository sample contained 310 nodes and 346 edges; 298
  nodes were dependencies. That is a package-manifest projection, not an
  architecture overview.
- The Service Map rendered dark labels on a black surface and retained an
  unrelated `app.py` Repo inspector. Trace retained the same stale inspector.
- 3D initially treated hidden node/edge filters as allowlists, so hiding one
  type could leave only that type visible.
- The previous local Shift-click path traversed edges in either direction,
  which could visually imply a reverse relationship Evigraph never asserted.

### Claude Design

The strongest screens are the
[focused Repo investigation](claude-design-redesign/mock-repo-search-inspector.png),
[3D Knowledge Atlas](claude-design-redesign/mock-repo-3d-knowledge-atlas.png),
[Service Map](claude-design-redesign/mock-service-map.png), and
[ranked Trace](claude-design-redesign/mock-distributed-trace.png).

What to adopt:

- explicit Overview, Focus and Path states;
- repository/module regions and visible sample status;
- one stable contextual inspector instead of unrelated cards;
- local detail with faint global context;
- ranked left-to-right paths with adjacent provenance;
- a quiet mineral shell with typography doing more work than decoration.

What to improve before implementation:

- Several overview and Service Map nodes are unlabeled even when Labels is
  active.
- The light graph treatment is too faint at ordinary laptop contrast.
- Typography is undersized in dense inspector sections.
- The 3D mock explains depth but does not visually prove it.
- It is a static design, so it proves neither interaction latency nor camera
  stability.

### Google Nano Banana

The strongest assets are the
[2D graph](google-nano-banana-redesign/mock-repo-2d-overview.jpg) and
[3D graph](google-nano-banana-redesign/mock-repo-3d-knowledge-atlas.jpg).

What to adopt:

- the graphite graph surface against a warm shell;
- forest/rust/ochre clusters with small, crisp nodes;
- high graph-to-chrome ratio;
- a bottom 3D tool strip that leaves the graph as the primary object;
- immediate visual distinction between repository communities.

What to reject:

- It does not define a coherent interaction/state model across screens.
- The 2D screen does not communicate the sampling contract or total-versus-
  displayed counts.
- The 3D treatment can become a dense spatial sculpture without a developer
  question.
- Generated text and code snippets are not trustworthy evidence.
- Some controls and labels changed across generations, so the images cannot be
  treated as a UI contract.

## Lens 1: graph visualization

The graph needs task-specific representations. A single force layout with
different filters is not sufficient.

The product now uses this state model:

| State | Developer question | Rendering rule |
|---|---|---|
| Overview | What exists, and where are the boundaries? | Stable repository/module regions, priority labels and subdued background edges |
| Focus | What is directly connected to this entity? | Exact one-hop nodes and edges stay crisp; unrelated context remains faint |
| Local path | Is there a directed route inside the sampled Repo graph? | Only forward edges already on the canvas; explicitly named local and sampled |
| Trace | How does one service reach another with proof? | Backend-ranked paths only, with confidence and `file:line` evidence per hop |

This follows the established visualization sequence of overview, zoom/filter
and details on demand in [Shneiderman's task taxonomy](https://www.cs.umd.edu/users/ben/papers/Shneiderman1996eyes.pdf),
and the degree-of-interest principle in
[Furnas's generalized fisheye views](https://courses.ischool.berkeley.edu/i247/f05/readings/Furnas_GeneralizedFisheyeViews_CHI86.pdf):
global importance plus graph distance determines what deserves detail.

For future estate-scale work, aggregate corridors may be used only in
Overview. Edge bundling reveals high-level structure but can impair exact path
tracing, so Focus and Trace must unbundle to real edges. See
[Holten's hierarchical edge bundles](https://ieeexplore.ieee.org/document/4015425/)
and the later
[force-directed edge-bundling evaluation](https://research.tue.nl/en/publications/force-directed-edge-bundling-for-graph-visualization/).

## Lens 2: frontend and rendering performance

Rendering more edges is not the first solution. Information reduction comes
before renderer replacement.

Changes made:

- Lockfile dependency leaves are suppressed by default in both dimensions.
- The 2D label budget is deterministic and bounded at overview, medium and
  detail zoom tiers.
- 2D label rectangles use a per-frame occupancy check.
- Background edges do not draw arrowheads; direction is promoted for focused,
  highlighted or sufficiently zoomed relationships.
- Canvas glow and `shadowBlur` work were removed from the hot paint path.
- The previously missing `forceCollide` force is now installed explicitly.
- 2D performs one automatic fit for a new scope/view and does not refit on
  every engine stop or selection.
- 3D uses stable ID-seeded jitter instead of `Math.random()`.
- 3D defaults Flow and Orbit off and throttles settled, idle rendering.
- WebGL pixel ratio is capped at 1.5 rather than 2.
- 3D labels are collision-tested and selected/path labels receive priority.

These changes follow [MDN Canvas optimization guidance](https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API/Tutorial/Optimizing_canvas)
to avoid unnecessary text/shadow work and
[MDN WebGL best practices](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices)
on pixel budgets and stable GPU resources.

The default application bundle is now 353 kB minified. Three.js is isolated in
a lazy 3D-only vendor chunk, so the default 2D workspace, Service Map and Trace
do not pay its startup cost.

## Lens 3: developer-tool usefulness

A developer graph earns its place when it shortens a concrete investigation.

The primary journeys are:

1. search a file, endpoint, service or dependency;
2. explain whether it is outside the sampled canvas;
3. focus its exact one-hop neighborhood;
4. traverse inbound/outbound entities from the inspector;
5. open an evidence-bearing edge;
6. move to Service Map or Trace without carrying incompatible selection state.

Changes made:

- Search result selection loads the exact bounded neighborhood directly; it no
  longer leaves the user on an unrelated sampled graph.
- Incoming/outgoing inspector rows now navigate using the API's `node_id`
  contract rather than a nonexistent `id` field.
- Switching Repo, Service Map and Trace clears incompatible node/edge drawers.
- Repo scope labels now describe the scope actually drawn.
- Multi-repository statistics no longer present one repository's claims and
  coverage as if they applied to the whole scope.
- The shared context bar names Overview, Module, Focus or Impact and separates
  grouped, eligible, displayed and loaded counts.
- The 3D HUD names Overview, Focus or Local directed path and avoids the
  game-like “Free Orbit” label.

## Lens 4: accessibility and visual system

Color is now constrained to graphite, mineral, bone, smoke, forest, rust and
ochre. It is never the sole carrier of direction, focus or confidence.

Changes made:

- The canvas uses a light mineral surface with high-contrast graphite text and
  restrained forest/rust/ochre graph marks.
- Selection has an outline as well as color.
- Focus uses opacity and scale in addition to color.
- Edge direction uses arrow geometry only where direction is being examined.
- 2D and 3D containers expose an accessible name and live selection summary.
- 3D labels are keyboard-focusable buttons.
- 3D keyboard shortcuts operate only after the graph receives focus.
- Motion is off by default.

This follows [WAI-ARIA Graphics](https://www.w3.org/TR/graphics-aria-1.0/),
[WCAG use of color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color),
[WCAG keyboard access](https://www.w3.org/WAI/WCAG22/Understanding/keyboard),
and [WCAG reduced-motion guidance](https://www.w3.org/WAI/WCAG22/Techniques/css/C39.html).

A complete accessible graph still needs a synchronized relationship table or
tree. Tabbing through hundreds of moving nodes is not the target interaction.

## Lens 5: graph trust and reliability

The graph must never visually claim a relationship the data did not assert.

Correctness changes made:

- Local 3D pathfinding is directed; reverse traversal no longer highlights an
  edge.
- The HUD calls it a local sampled path, not Trace.
- Unresolved 3D buffer slots are cleared so a same-sized data replacement
  cannot retain an old line segment.
- 2D and 3D use the same hidden-type semantics.
- A bridge request failure is now “unavailable,” not a verified zero.
- Cross-module counts are described as rendered bridge edges, not calls; one
  logical crossing may contain multiple evidence-bearing edge halves.
- Repository-controlled hover and cluster text uses `textContent` rather than
  interpolation into `innerHTML`.
- Type-band mode is named for what it actually encodes; it is not presented as
  proven architecture layering.

## Implemented hybrid

Key implementation seams:

- `frontend/src/lib/graphVisibility.ts` — shared 2D/3D visibility truth.
- `frontend/src/lib/graphOverviewProjection.ts` — grouped entry plus bounded
  Module, Focus and Impact projections using asserted edges only.
- `frontend/src/store/graphNavigationStore.ts` and
  `frontend/src/components/GraphContextBar.tsx` — shared 2D/3D investigation
  level, Back contract and displayed/eligible/loaded counts.
- `frontend/src/lib/graph2dProjection.ts` — focus context and deterministic
  label budgets.
- `frontend/src/lib/graph2dPainter.ts` — mineral node, edge and module
  rendering.
- `frontend/src/hooks/useGraph2DLayout.ts` — force setup and one-policy camera
  behavior.
- `frontend/src/lib/graphStablePosition.ts` — stable 3D node initialization.
- `frontend/src/lib/graph3dPath.ts` — directed sampled-canvas paths.
- `frontend/src/lib/graph3dBufferBuilder.ts` — shared filter, focus and stale
  buffer handling.
- `frontend/src/lib/graph3dLabelPlacer.ts` — priority and collision-aware label
  allocation.
- `frontend/src/components/ServiceMapNavigator.tsx` — keyboard-accessible
  service selection.
- `frontend/src/components/TraceSidebar.tsx` — ranked path controls and
  keyboard-accessible Inspect hop evidence actions.

`GraphCanvas2D.tsx` was reduced from 700 lines to fewer than 300 by extracting
those independently testable subjects. New and directly extracted graph
modules remain within the 300-line rule. The pre-existing oversized
`ServiceMapView.tsx` was reduced and its new navigation/status concerns were
extracted; it remains scheduled for further decomposition.

## Remaining work

The frontend now provides grouped entry and bounded Module/Focus/Impact
projections. The next large improvement is the corresponding aggregate-first
**backend** contract, not another renderer effect.

1. Return displayed and available totals, truncation and partial-scope state.
2. Add repository/module aggregate nodes and lossless aggregate edges carrying
   member edge IDs, relation counts and minimum confidence.
3. Expand one aggregate into exact nodes and evidence on demand.
4. Return the backend's authoritative module identity instead of duplicating
   `module_of` in React.
5. Add exact 3D edge picking only in bounded Focus/Path mode.
6. Add a synchronized accessible relationship table.
7. Consider a module-scoped connections matrix for dense dependency
   comparison. Research shows matrices remain useful when node-link density
   becomes the limiting factor; see
   [Ghoniem et al.](https://doi.org/10.1109/INFVIS.2004.1) and
   [NodeTrix](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/12/Henry_infovis07.pdf).

3D should remain conditional. Research reports mixed results by task and
viewpoint: motion/depth can help some path or topology tasks, while occlusion
and reorientation increase cost for others. See
[Ware and Franck](https://scholars.unh.edu/ccom/939/),
[Kwon et al.](https://vis.cs.ucdavis.edu/papers/TVCG_Kwon2016.pdf), and the
[EuroVis viewpoint evaluation](https://diglib.eg.org/items/5b7ae76f-2daf-40df-a110-0903b731d2c6).

## Validation contract

Every future graph change should be tested with the same tasks:

- locate an off-sample search result and focus it;
- identify exact incoming and outgoing relationships;
- hide one node and one edge type in both dimensions;
- find a cross-repository bridge or state that it is zero/unavailable;
- trace a directed path and verify every hop's provenance;
- switch 2D → 3D → 2D without losing scope or selected identity;
- switch Repo → Service Map → Trace without retaining an incompatible drawer;
- distinguish loaded, displayed, filtered, sampled, truncated and unavailable;
- test keyboard focus and reduced-motion behavior;
- record interaction latency and frame time on one, two and ten-repository
  scopes.

The acceptance rule is unchanged: zero visually fabricated paths or
relationships.

The latest browser execution of this contract, including the shared
navigation ladder, bounded Module/Focus/Impact projections, Service Map
service search and accessible Trace-hop evidence, is recorded in
[navigation-and-feature-qa-2026-08-30.md](navigation-and-feature-qa-2026-08-30.md).
