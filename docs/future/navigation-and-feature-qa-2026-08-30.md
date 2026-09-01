# Adduce interaction contract and feature QA

Date: 2026-08-30
Runtime reviewed: `http://127.0.0.1:28080/`

This is the acceptance record for the applied hybrid redesign. It tests the
application as an investigation workflow, not as a collection of screens.
All counts below are from the captured local graph and may change after a
repository is re-ingested.

## Navigation contract

1. Repository scope has one meaning in Repo, Service Map and Trace. Scope
   changes are staged in the picker and cause one data reload on **Apply**.
2. An empty stored scope means all repositories, but **All repositories** is
   disabled when it would exceed the operator-set repository limit.
3. Every broad Repo dataset enters at grouped Overview: Overview,
   Architecture, Code, API and Dependencies change what is loaded, not the
   density rule.
4. Repo navigation is **grouped overview → bounded module detail → bounded
   focus or impact**. The UI reports displayed and full counts separately.
5. The module/focus level and selected node survive a 2D ↔ 3D switch. A path,
   which only 3D renders, is cleared when leaving 3D.
6. **Back** and `Escape` unwind one level at a time: Path → Focus → Module →
   grouped Overview. They do not reset scope, filters or unrelated settings.
7. Search is exhaustive across the selected repositories and navigates
   directly to the selected node's exact local neighborhood. Results identify
   their repository and are capped visibly at 50 rows.
8. Impact is disabled until a node is selected. It then loads the selected
   repository's exact two-hop graph and labels the depth and display bound.
9. Changing workspace, scope, view mode or Trace constraints clears inspectors
   and results that are no longer compatible with the new state.
10. Canvas clicking is a shortcut, not the only navigation route. Repo nodes
    are reachable through search, Service Map nodes through **Find a service**,
    and Trace edges through **Inspect hop**.

## Density and truth contract

- The grouped overview rolls up only relationships present in the loaded
  graph. It does not synthesize corridors.
- Expanded Module, Focus and Impact projections show only asserted edges whose
  two displayed endpoints are retained.
- The exact-node display limit comes from `/api/config` as
  `graph_detail_node_limit` and defaults to 80. Search still reaches omitted
  nodes.
- Service Map distinguishes link candidates from links actually displayed and
  reports unconnected services instead of letting them distort the layout.
- Trace is the ranked, backend evidence workflow. The 3D local path remains
  explicitly a directed path through the sampled canvas.
- Cards and context bars say **loaded**, **sample**, **displayed**, **of N**,
  **exact edges**, **candidate**, **unconnected** or **unavailable** where those
  distinctions matter.

## Browser QA matrix

| Area | Action checked | Captured result |
|---|---|---|
| Header | Repo → Service Map → Trace | Active workspace changes; 2D/3D controls appear only in Repo; incompatible drawer clears |
| Scope | Stage `lanovyx` + `latte`, then Apply | Header stayed on the old scope while editing; one Apply produced 17 groups, 14 displayed edges and 439 loaded nodes |
| Scope | Return to `lanovyx` only | Header, Repo, Service Map and Trace all showed `sfbayman/lanovyx`; Refresh/Delete returned only for the single-repo scope |
| Repo modes | Architecture, Code, API, Dependencies, Overview | Grouped entry states were 5/3, 2/0, 2/0, 4/3 and 10/9 displayed groups/edges rather than 300–600-node hairballs |
| Module | Open `sfbayman/lanovyx/backend` | 80 of 270 nodes and 79 exact visible edges; the same level survived 3D → 2D |
| Search | Search `app.py` and select `backend/agents/src/lanovyx_agents/app.py` | Direct Focus at 80 of 151 nodes and 79 exact visible edges; repository and path were explicit in results |
| Impact | Select Impact from `app.py` | 2 hops, 80 of 151 nodes and 85 exact visible edges; Impact was disabled before selection |
| Inspector | Follow `DECLARES get_parameter_set` | Focus moved to 3 nodes/2 edges; search text cleared; incoming, outgoing and neighbor rows were keyboard buttons |
| Inspector | Copy path | Button changed to **Copied** and announced `Path copied` |
| 2D controls | Reset, Fit, Rotate, Settle/Re-layout, Labels, Particles | Every control executed; toggle state matched its visible label and `aria-pressed` state |
| Fullscreen | Enter and exit | Header/sidebar hid; **Exit fullscreen** and `Esc` route were present; normal navigation returned |
| Filters | Hide Repo, highlight/hide CONTAINS, switch dimensions | 2D and 3D both showed 9 groups/0 edges; hiding a highlighted type cleared its highlight; restoring returned 10/9 |
| 3D controls | Less noise, Labels, zoom in/out/100%, Reset | Toggles and zoom state updated; Reset changed camera only and did not silently change investigation level |
| 3D keyboard | `L`, Shift+Enter, Escape | `L` toggled labels; Shift+Enter created `app.py → POST /discover`; first Escape cleared Path, second cleared Focus |
| Service Map | Load `lanovyx` at 0.60 | Light canvas, 9 displayed nodes, 10 displayed links, 12 candidates and 2 unconnected services |
| Service Map | Highlight/hide/show Service call | Highlight state was explicit; hidden map reached 0 links; show restored 10 displayed links and cleared stale highlight |
| Service Map | Find `ops` | Accessible service search opened callers/callees: 0 called-by and 3 calls |
| Evidence | Inspect `ops → lanovyx/postgres` | Relationship drawer showed confidence 0.96, two via signals and two GitHub `file:line` links |
| Handoff | `ops` → Trace from here | Trace opened with `ops` already selected as origin |
| Trace picker | Choose destination | Repaired modal stacking; `lanovyx/postgres` selection closed the dialog and enabled Trace |
| Trace | Run `ops → lanovyx/postgres` | 2 ranked paths, 3 services and 3 displayed hops |
| Trace evidence | Inspect first hop | `CALLS_SERVICE` drawer opened the same confidence, signals and two `file:line` links without canvas precision clicking |
| Trace constraints | Change confidence, altitude, max hops and max paths | Prior paths and drawer cleared; controls reflected 85%, Code, 5 hops and 4 paths |
| Trace validation | Choose identical endpoints | Trace disabled with **Choose two different services** |
| Ingest | Open and press Escape | Dialog closed and focus returned to Ingest; no repository was submitted |

## View Mode regression repair and exhaustive option pass

A follow-up browser pass reproduced two separate 3D View Mode failures:

1. The component returned a loading screen during every graph request. That
   removed the DOM element owning the imperative WebGL scene while leaving the
   React component mounted, so the scene lifecycle did not run again. Counts
   changed but the renderer remained blank.
2. DOM label listeners captured the initial Overview navigation callback.
   Later modes displayed their current labels, but selecting one wrote its
   group into Overview's stale context and could not drill down.

The renderer container now stays mounted under loading/error overlays, and
imperative label listeners dereference the current React callback. A rapid
`Architecture → Code → API → Dependencies → Overview → 2D → 3D` stress pass
finished at 10 groups/9 edges with all 10 labels present.

The follow-up exercised every visible option family:

| Option family | Coverage |
|---|---|
| View Mode entry | All five broad modes in 2D and 3D, including rapid switching |
| View Mode drill-down | Largest group in every mode: Architecture 80/76, Code 80/75, API 80/75, Dependencies 19/20, Overview 80/79 nodes/edges |
| Dimension parity | Every expanded mode preserved the same counts and Back route through 3D → 2D → 3D |
| Node filters | All 17 node-type checkboxes toggled off/on; filter-to-empty recovered to 10/9 in 3D |
| Edge filters | All 17 edge types highlighted, hidden, shown and verified to clear stale highlight |
| Filter disclosure | Node/edge headings show hidden counts; Dependencies reports 29 eligible of 320 loaded while 291 lockfile leaves are hidden |
| Repository picker | Search/no-match, staged Apply, Cancel, Escape/focus return, 10-repository cap, disabled 13-repository All option |
| Scope races | Scope + mode changes during loading settled on the final requested mode with current labels |
| Cross-repo view | Petclinic Cloud + Microservices exposed 70 bridge edges; Connections Only showed the same 8 groups/7 edges in 2D and 3D |
| 2D controls | Reset, Fit, Rotate, Settle/Re-layout, Labels, Particles and Fullscreen |
| 3D controls | Less noise, Labels, `L`, zoom in/out/100%, camera Reset, Back/Escape and Shift+Enter directed path |
| Repo search | No-result, clear, exact result, Focus, Impact, relationship navigation and clean return to Overview |
| Service Map relations | All five relation-type highlight/hide/show controls |
| Service Map services | All nine services selected through keyboard-accessible search; no-match and Escape paths |
| Service Map edges | All 20 inbound/outbound rows representing the 10 displayed directed links opened an evidence drawer |
| Trace endpoints | All nine services selected as both origin and destination |
| Trace picker | Filter/no-match, Cancel, Escape and focus return; dialogs remain usable over a no-path result |
| Trace constraints | Both altitudes; confidence 0.60–1.00; hop limit 1–8; path limit 1–5 |
| Trace outcomes | Two-path success, no-path result, identical-endpoint validation, all three displayed hop inspectors, stale-result clearing |
| Cross-page state | Repo node drawer and Service/Trace edge drawers cleared when their subject became incompatible |

The follow-up also corrected the global layer order: canvas messages now sit
below Trace controls and the header, while repository/service dialogs sit
above both. Repository and Trace service dialogs return focus to their trigger
after selection, Apply, Cancel, Close or Escape.

## Mutating actions deliberately not executed

The browser audit did not submit Ingest, Refresh, Delete or Rebuild Links.
Those actions mutate repositories or stored link state. Their visibility,
disabled states, dialog behavior and scope gating were checked; executing them
was not necessary to prove the navigation repair and would have changed the
user's local graph.

## Automated verification

- Frontend typecheck and production build.
- The default application bundle is 353 kB minified; Three.js is isolated in
  a lazy 3D-only vendor chunk and is not fetched for the default 2D workspace.
- 23 frontend deterministic graph tests, including grouping, display bounds,
  focus/impact truth, repository scope, directed paths, label accessibility,
  stable positions and filter parity.
- Backend route/config checks and the full backend test suite: 2,269 passed,
  38 skipped.
- `git diff --check` and the 300-line production-source rule for every new or
  directly refactored graph module. `ServiceMapView.tsx` remains a pre-existing
  oversized file but is smaller than before this redesign and its new status
  and navigation concerns were extracted.

## Remaining boundary

The graph endpoint is still a bounded server response. The UI now names that
boundary and provides exhaustive search, but a canvas is not proof that every
node in storage was loaded. This is intentional and must remain visible in any
future redesign.
