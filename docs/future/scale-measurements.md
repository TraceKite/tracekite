# Historical scale measurements

[Docs](../README.md) · [Current architecture](../design/architecture.md)

These figures preserve measurements previously embedded in the architecture
document. They are historical records, not current release gates or promises
for an arbitrary estate. The prior record is in
[architecture at 0.2.0](https://github.com/TraceKite/tracekite/blob/v0.2.0/docs/design/architecture.md). The source/workload identity was not recorded alongside
every old measurement; rerun the tools before using them as a new benchmark.

## Recorded workloads

| Workload | Recorded observation | Limitation |
|---|---|---|
| Six-repo estate, 3,089 claims | Claim load 0.12 s, join 0.03 s; full Neo4j run 2.6–12 s | In-memory join time excludes persistence |
| Synthetic 100 repos, 2,526 files | Artifact MAP 5.9 s serial → 1.1 s at 8 workers; 326/326 planted calls | Synthetic fixture composition |
| Synthetic 1,001 repos, 25,814 files, 16,556 claims | MAP 60.0 s → 11.3 s at 8 workers; join 0.19 s; 3,374/3,374 planted calls | About 16 claims/repo, much sparser than the measured real estate |
| One change in that 1,001-repo estate | 1,000 artifacts reused; 5.8 s end to end | Original artifact-read path; workload-specific |
| 21-repo estate, largest repo holds 55% of files | File sharding 2.45× at 8 workers vs repo sharding 1.71× | Particular repository-size distribution |

A separate 100-repo optimization recorded a 0.54 s repush after reading only
claim rows from artifacts. This is not a 1,001-repo end-to-end guarantee.

The old architecture also projected 81 minutes for a hypothetical serial
1,000-repo run. That was an extrapolation from a database-heavy run, not a
measured resolver cost; do not compare it directly with in-memory MAP/JOIN times.

## Reproduce useful measurements

Use [`scale_probe.py`](../../backend/tools/scale_probe.py),
[`synth_estate.py`](../../backend/tools/synth_estate.py), and the parallel/sharded
scan tests. Record the source SHA, configuration, worker count, platform, input
file/claim counts, parsing coverage, and stage times with the result.

A speedup is useful only when the artifacts and supported answers remain equal.
Test claim-dense and skewed workloads as well as file-heavy ones. The current
architecture keeps the join in one process; distributed reduce is a future
choice to justify with measurements.
