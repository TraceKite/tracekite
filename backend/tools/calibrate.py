"""Confidence-calibration CLI.

Runs the labeled-estate harness in evigraph/services/calibration.py, prints the
per-tier P/R table plus the unmeasured-tier gap list, and (unless --dry-run)
writes the `measured:` block into confidence.yml.

    python -m tools.calibrate            # measure and write the block
    python -m tools.calibrate --dry-run  # print the table, write nothing
    python -m tools.calibrate --json     # machine-readable output

Exit codes: 0 clean; 1 when any measured precision undercuts its served
confidence by more than 0.15 — a tier serving 0.95 that measures 0.7 is a lie
worth failing on.
"""

import argparse
import json
import os
import sys

# A tier may serve at most this much above what it measures before the run
# fails (served - measured precision > slack => exit 1).
CONFIDENCE_SLACK = 0.15


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.calibrate",
        description="Measure per-tier precision/recall over labeled fixture "
                    "estates and record the rows in confidence.yml.")
    parser.add_argument(
        "--config-dir", default=None,
        help="Control-plane directory holding confidence.yml (default: the "
             "repo's config/, resolved via evigraph.services.linker.base."
             "config_dir()).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the table but do not write the measured block.")
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit rows and gaps as JSON instead of the table.")
    parser.add_argument(
        "--corpus", default=None,
        help="Corpus label recorded in the measured block "
             "(default: fixtures-v1).")
    args = parser.parse_args(argv)

    # Environment must be settled BEFORE any app module import: settings are
    # read at import time, and redaction needs an HMAC key.
    os.environ.setdefault("GRAPH_HMAC_KEY", "calibration-key")
    if args.config_dir:
        os.environ["KG_CONFIG_DIR"] = os.path.abspath(args.config_dir)

    # Allow direct execution (`python tools/calibrate.py`) as well as
    # `python -m tools.calibrate` from backend/.
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    # Binds the environment settled above to the core and store config
    # objects. Core does not read the environment itself (architecture §2),
    # so an entry point that skips this hashes config values under an empty
    # HMAC key instead of the deployment's. Must follow the setdefault above.
    import evigraph.config  # noqa: F401

    from evigraph.services.calibration import run_calibration
    from evigraph.services.calibration_io import (
        DEFAULT_CORPUS, coverage_gaps, write_measured,
    )
    from evigraph.services.linker.base import config_dir, load_confidence
    from evigraph.services.linker.reliability import (
        derive_constants, derived_block_lines,
    )
    from evigraph.services.linker.review_labels import review_labels

    config_path = os.path.join(config_dir(), "confidence.yml")
    served_table = load_confidence()
    results = run_calibration()
    gaps = coverage_gaps(results, config_path)
    diagnostics = results.get("_diagnostics") or {}

    rows = []
    for section in sorted(k for k in results if not k.startswith("_")):
        for tier in sorted(results[section]):
            row = results[section][tier]
            served = (served_table.get(section) or {}).get(tier)
            rows.append({"tier": f"{section}.{tier}",
                         "served": served, **row})

    lies = [r for r in rows
            if isinstance(r["served"], (int, float))
            and r["precision"] < float(r["served"]) - CONFIDENCE_SLACK]

    # E5: constants derived, not chosen. Labels are the measurement here,
    # so unreadable review decisions fail this run — the opposite of
    # linking, where reviews refine but never block.
    derivation = derive_constants(served_table, rows, review_labels())
    overpriced = [r for r in derivation["rows"] if r["served"] > r["derived"]]

    if not args.dry_run:
        write_measured(results, config_path,
                       corpus=args.corpus or DEFAULT_CORPUS,
                       derived_lines=derived_block_lines(derivation))

    if args.as_json:
        print(json.dumps({"rows": rows, "gaps": gaps,
                          "diagnostics": diagnostics,
                          "confidence_lies": [r["tier"] for r in lies],
                          "derivation": derivation,
                          "overpriced": [r["tier"] for r in overpriced],
                          "wrote": None if args.dry_run else config_path},
                         indent=2))
    else:
        header = (f"{'tier':<28} {'served':>7} {'precision':>10} "
                  f"{'95% interval':>15} {'recall':>7} {'support':>8} "
                  f"{'fp':>4}")
        print(header)
        print("-" * len(header))
        for row in rows:
            served = ("-" if row["served"] is None
                      else f"{float(row['served']):.2f}")
            interval = (f"[{row['precision_lo']:.3f}, "
                        f"{row['precision_hi']:.3f}]")
            print(f"{row['tier']:<28} {served:>7} {row['precision']:>10.3f} "
                  f"{interval:>15} {row['recall']:>7.3f} "
                  f"{row['support']:>8} {row['fp']:>4}")

        for miss in diagnostics.get("missing", []):
            print(f"\nMISSING EXPECTED EDGE [{miss['estate']}]: "
                  f"{miss['expected']}")
        for hit in diagnostics.get("forbidden", []):
            print(f"\nFORBIDDEN EDGE APPEARED [{hit['estate']}] "
                  f"tier={hit['tier']}: {hit['edge']}")

        if gaps:
            print(f"\nUNMEASURED TIERS ({len(gaps)}) — served without a P/R "
                  f"row (invariant 7 unmet):")
            for gap in gaps:
                print(f"  - {gap}")
        else:
            print("\nAll served tiers have measured rows.")

        capped = [r for r in derivation["rows"] if r["basis"] != "prior"]
        print(f"\nDerived constants: {len(derivation['rows'])} tiers, "
              f"{len(capped)} capped by labels, "
              f"{derivation['unattributed']['fp']} unattributed FP label(s).")

        if args.dry_run:
            print(f"\n--dry-run: not writing {config_path}")
        else:
            print(f"\nWrote measured block: {config_path}")

    if lies:
        print("\nCONFIDENCE LIES (measured precision undercuts served by "
              f"more than {CONFIDENCE_SLACK}):", file=sys.stderr)
        for row in lies:
            print(f"  {row['tier']}: serves {row['served']}, measured "
                  f"precision {row['precision']}", file=sys.stderr)
        return 1
    if overpriced:
        # E5: a constant above its evidence ceiling is no longer a choice
        # anyone gets to make. The derived value is the number to adopt.
        print(f"\nCONSTANTS ABOVE EVIDENCE CEILING ({len(overpriced)}):",
              file=sys.stderr)
        for row in overpriced:
            print(f"  {row['tier']}: serves {row['served']}, labels allow "
                  f"{row['derived']} (basis {row['basis']}, "
                  f"tp {row['tp']} fp {row['fp']}) — lower the constant "
                  f"to the derived value", file=sys.stderr)
        return 1
    if gaps:
        # F3: an unmeasured tier fails the build, not just the eye. A tier
        # served without a labelled estate behind it is a number nobody
        # measured, and "the rule everyone knows" stops being a rule the
        # first time a new resolver ships a tier under deadline. The fix is
        # to label the corpus for the tier, not to remove this check.
        print(f"\nUNLABELLED TIER(S) SERVED ({len(gaps)}): "
              + ", ".join(sorted(gaps)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
