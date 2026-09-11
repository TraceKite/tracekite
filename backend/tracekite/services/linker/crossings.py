"""Cross-repo call crossings, assembled from raw rows.

Moved out of `routes/links.py` because it computes a fact about the graph:
the decision that the boundary is the MODULE, not the repository, is graph
semantics — a route deciding it would give app users an answer the library
cannot reproduce. The route keeps the query; this keeps the meaning.
"""

from tracekite.services.linker.modules import module_of


def assemble_crossings(rows: list[dict]) -> dict:
    """INVOKES/EXPOSES row pairs into a nodes+links view.

    The boundary is the module, not the repository. Requiring different
    repo ids discarded every crossing inside a monorepo — on one estate
    that silently threw away foyer -> capability-registry, which is
    exactly the call the graph exists to surface.
    """
    nodes: dict[str, dict] = {}
    links: list[dict] = []
    for row in rows:
        a_mod = module_of(row["a_path"])
        b_mod = module_of(row["b_path"])
        if a_mod == b_mod and row["a_repo"] == row["b_repo"]:
            continue
        for side in ("a", "b"):
            nid = row[f"{side}_id"]
            nodes.setdefault(nid, {
                "id": nid, "name": row[f"{side}_name"], "type": row[f"{side}_type"],
                "label": row[f"{side}_name"], "path": row[f"{side}_path"],
                "repo_id": row[f"{side}_repo"],
                "module": module_of(row[f"{side}_path"]), "metadata": {},
            })
        nodes.setdefault(row["c_id"], {
            "id": row["c_id"], "name": row["c_name"], "type": row["c_label"],
            "label": row["c_name"], "path": None,
            # A rendezvous belongs to no single repo -- that is what makes it a
            # meeting point. Flagged so the UI can style it and not ask a repo
            # for details it does not have.
            "repo_id": None, "is_rendezvous": True, "metadata": {},
        })
        links.append({"source": row["a_id"], "target": row["c_id"], "type": "INVOKES",
                      "confidence": row["in_conf"], "evidence": row["in_ev"] or []})
        links.append({"source": row["b_id"], "target": row["c_id"], "type": "EXPOSES",
                      "confidence": row["ex_conf"], "evidence": row["ex_ev"] or []})

    return {"nodes": list(nodes.values()), "links": links}
