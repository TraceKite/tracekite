"""Operator control-plane mutations.

Core READS the control plane (`load_confidence`, `load_promotions`) — a
resolver needs its tables. Only the server may MUTATE it: a promotion is
an operator's decision arriving over HTTP, and a library host replays
decisions through the files it supplies, never through a write path the
engine performs on its own.
"""

import os

import yaml

from adduce.services.linker.base import config_dir


def append_promotion(entry: dict) -> None:
    path = os.path.join(config_dir(), "promotions.yml")
    data = {"promotions": []}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {"promotions": []}
    data.setdefault("promotions", []).append(entry)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)
