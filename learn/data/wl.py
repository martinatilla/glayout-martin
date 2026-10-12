"""Weisfeiler-Lehman hash of a schematic's topology, for finding duplicate circuits.

The graph is bipartite: device nodes labelled by device kind, net nodes labelled
by net class (power, ground, bias, clock, signal) and whether the net is a port;
each pin is an edge labelled by its terminal role. Device and net names never
enter, and a MOS drain and source are the same role (the device is symmetric),
so two netlists of one circuit hash alike however they are written. Different
circuits can collide (WL cannot tell some non-isomorphic graphs apart); for
de-duplication and for keeping copies on one side of a split, that errs in the
safe direction.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

from glayout.schematic.model import PINS, net_class
from glayout.schematic.vocab import device_kind_class, terminal_role

WL_ITERATIONS = 4
WL_VERSION = f"wl-v1 ({WL_ITERATIONS} iterations; drain=source; nets by class and port flag)"


def _h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def wl_hash(sch: dict, iterations: int = WL_ITERATIONS) -> str:
    """Hash of ``Schematic.to_json()``."""
    ports = set(sch["ports"])
    labels: dict[tuple, str] = {}
    adj: dict[tuple, list] = defaultdict(list)
    nets = list(sch["ports"])
    for i, d in enumerate(sch["devices"]):
        kind = d["kind"]
        cls = device_kind_class(kind)
        labels[("d", i)] = "D:" + (kind if cls in ("composite", "unknown") else cls)
        names = PINS.get(kind) or tuple(f"P{k + 1}" for k in range(len(d["nets"])))
        for pin, net in zip(names, d["nets"]):
            role = terminal_role(kind, pin)
            role = "sd" if role in ("drain", "source") else (pin if role == "other" else role)
            adj[("d", i)].append((role, ("n", net)))
            adj[("n", net)].append((role, ("d", i)))
            if net not in nets:
                nets.append(net)
    for net in nets:
        labels[("n", net)] = f"N:{net_class(net)}{':port' if net in ports else ''}"
    history = Counter(labels.values())
    for _ in range(iterations):
        labels = {v: _h(lab + "(" + ",".join(sorted(f"{r}|{labels[u]}" for r, u in adj[v])) + ")")
                  for v, lab in labels.items()}
        history.update(labels.values())
    return hashlib.sha256(json.dumps(sorted(history.items())).encode()).hexdigest()[:16]
