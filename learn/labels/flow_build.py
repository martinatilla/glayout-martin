"""Builder for the audit: rebuild one labelled layout through the same flow, routed and drawn.

``build_routed(pdk, key, ...)`` is called by gLayout's DRC runner (``tests/drc/run_cell_drc.py``)
in a worker process. It writes a sidecar JSON with the routing summary, so the audit can check
that the rebuild reproduces the label record.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

SCHEMATICS = Path(__file__).resolve().parents[1] / "data" / "build" / "schematics.jsonl"
_SCHEMATICS: dict = {}


def load_schematic(key: str):
    from glayout.schematic import Schematic, curated
    cur = curated()
    if key in cur:
        return cur[key]
    if not _SCHEMATICS:
        with SCHEMATICS.open() as f:
            for line in f:
                r = json.loads(line)
                _SCHEMATICS[r["key"]] = r["schematic"]
    return Schematic.from_json(_SCHEMATICS[key])


def build_routed(pdk, key: str, sizing_seed: int = 0, seed: int = 0, name: Optional[str] = None,
                 sidecar: Optional[str] = None):
    from glayout.schematic import schematic_routed
    comp, circuit, fp, rr, loop = schematic_routed(pdk, load_schematic(key), sizing_seed=sizing_seed, seed=seed,
                                                   strict=True, return_result=True, name=name)
    if sidecar:
        Path(sidecar).write_text(json.dumps({"routing": rr.summary(), "area_um2": round(fp.metrics["area"], 4),
                                             "rounds": len(loop.rounds), "scales": loop.scales}, sort_keys=True))
    return comp
