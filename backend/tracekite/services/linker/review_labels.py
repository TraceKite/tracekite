"""Review decisions as labelled data.

Every promote/reject an operator makes is a labelled example — a human
looked at an edge and said true or false — and labels are the scarcest
input this system has. This turns the decisions file into the shape E5's
reliability learning and any future calibration pass consume, without the
reviewer ever having to know they were labelling.
"""

from tracekite.services.linker.base import load_promotions


def review_labels(promotions: list | None = None) -> dict:
    """Decisions as {tp: [...], fp: [...]}, each with its identity intact.

    A promote is a human-confirmed true positive; a reject is a
    human-confirmed false positive. Entries with any other decision are
    returned under `unusable` rather than dropped — a malformed label is a
    finding about the review tooling.
    """
    entries = load_promotions() if promotions is None else promotions
    labels = {"tp": [], "fp": [], "unusable": []}
    for entry in entries:
        record = {"source": entry.get("source", ""),
                  "type": entry.get("type", ""),
                  "target": entry.get("target", ""),
                  "tier": entry.get("tier", ""),
                  "note": entry.get("note", "")}
        decision = entry.get("decision", "")
        if decision == "promote":
            labels["tp"].append(record)
        elif decision == "reject":
            labels["fp"].append(record)
        else:
            labels["unusable"].append({**record, "decision": decision})
    return labels
