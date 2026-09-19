## Summary

Describe the problem and the change.

## Evidence and declines

- What source evidence supports new claims or edges?
- Which ambiguous or unsupported cases decline?
- If no graph behavior changes, write “Not applicable.”

## Validation

- [ ] Relevant focused tests pass.
- [ ] `.venv/bin/python -m pytest backend/tests -q` passes.
- [ ] `pnpm --filter @tracekite/web run typecheck` passes.
- [ ] Extraction/linking changes were re-ingested and checked with the accuracy
      harness, or this is not an extraction/linking change.
- [ ] No secrets, private source, generated build output, or unrelated changes
      are included.
- [ ] Public behavior and contract changes are documented.
