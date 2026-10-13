"""Audit a label run: rebuild a sample of routed layouts and run DRC and LVS on them.

Run inside the container, after ``run_flow.py``:

    .venv/bin/python learn/labels/audit.py --run pilot --n 20

For each sampled record (status ok and routed) the layout is rebuilt through the same flow
(``flow_build.build_routed``), drawn, and checked with gLayout's own runners: klayout DRC and
magic DRC (``tests/drc/run_cell_drc.py``) and LVS (``tests/lvs/run_cell_lvs.py``: klayout deck on
gf180, magic + netgen on sky130). The rebuild must also reproduce the record (same routed
wirelength, vias, area and rounds), which checks that the labels are deterministic.

Writes learn/labels/out/<run>/audit/ (GDS, reports) and audit.json.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

LEARN = Path(__file__).resolve().parents[1]
GLAYOUT = LEARN.parent / "gLayout"
sys.path[:0] = [str(Path(__file__).resolve().parent), str(GLAYOUT / "tests" / "drc"), str(GLAYOUT / "tests" / "lvs")]
os.environ.setdefault("GLAYOUT_TABLES", "0")

import run_cell_drc  # noqa: E402
import run_cell_lvs  # noqa: E402


def cell_name(rec: dict) -> str:
    return "aud_" + re.sub(r"[^A-Za-z0-9_]", "_", f"{rec['key']}_{rec['pdk']}_s{rec['sizing_seed']}_r{rec['seed']}").lower()


def check_one(job: dict) -> dict:
    rec, out = job["record"], Path(job["out"])
    name = cell_name(rec)
    sidecar = out / "sidecars" / f"{name}.json"
    item = {"name": name, "pdk": rec["pdk"], "deck": str(run_cell_drc._drc_deck_for(rec["pdk"])),
            "kwargs": {"key": rec["key"], "sizing_seed": rec["sizing_seed"], "seed": rec["seed"], "name": name,
                       "sidecar": str(sidecar)},
            "gds_path": str(out / "gds" / f"{name}.gds"), "rpt_path": str(out / "reports" / f"{name}.lyrdb"),
            "netlist_path": str(out / "netlists" / f"{name}.spice"), "out_dir": str(out),
            "engines": ["klayout", "magic"], "magic_dir": str(out / "magic")}
    drc = run_cell_drc._run_one_cell(item)
    res = {"id": rec["id"], "cell": name, "pdk": rec["pdk"], "drc_status": drc["status"],
           "klayout": drc.get("engines", {}).get("klayout", {}).get("violations", {}).get("effective"),
           "magic": (drc.get("engines", {}).get("magic", {}).get("violations") or {}).get("effective"),
           "message": drc.get("message", "")[:200]}
    if not Path(item["gds_path"]).exists() or not sidecar.exists():      # the build itself failed
        res.update({"lvs": "not run", "reproduced": False})
        return res
    lvs = run_cell_lvs._run_one_lvs({"name": name, "pdk": rec["pdk"], "gds_path": item["gds_path"],
                                     "netlist_path": item["netlist_path"], "out_dir": str(out),
                                     "rpt_dir": str(out / "lvs_reports")})
    res["lvs"] = lvs["status"]
    side = json.loads(sidecar.read_text())
    g = rec["targets"]["graph"]
    res["reproduced"] = (abs(side["routing"]["wirelength_um"] - g["wirelength_um"]) < 1e-3
                         and side["routing"]["vias"] == g["vias"] and abs(side["area_um2"] - g["area_um2"]) < 1e-3
                         and side["rounds"] == g["rounds"])
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--n", type=int, default=20, help="records to audit, split evenly over the PDKs")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    run = LEARN / "labels" / "out" / args.run
    recs = [json.loads(line) for line in (run / "records.jsonl").open()]
    routed = [r for r in recs if r["status"] == "ok" and r["targets"]["graph"]["routed"]]
    rng = random.Random(args.seed)
    by_pdk: dict = {}
    for r in sorted(routed, key=lambda r: r["id"]):
        by_pdk.setdefault(r["pdk"], []).append(r)
    sample = []
    for pdk, rs in sorted(by_pdk.items()):
        sample += rng.sample(rs, min(len(rs), args.n // len(by_pdk)))
    out = run / "audit"
    for sub in ("gds", "reports", "netlists", "magic", "sidecars", "lvs_reports"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for r in sample:
        run_cell_drc._CELL_BUILDERS[cell_name(r)] = "flow_build:build_routed"
    with mp.get_context("fork").Pool(args.jobs, maxtasksperchild=4) as pool:
        results = pool.map(check_one, [{"record": r, "out": str(out)} for r in sample])
    # magic's DRC wrapper writes its command script to one shared path, so parallel runs can pick up
    # each other's script ("Defaulting to stale magic_commands.tcl") and leave no report: rerun those alone
    for i, (r, res) in enumerate(zip(sample, results)):
        if res["magic"] is None and "magic" in res["message"]:
            results[i] = check_one({"record": r, "out": str(out)})
            results[i]["retried"] = True
    clean = [r for r in results if r["klayout"] == 0 and r["magic"] == 0 and r["lvs"] == "pass"]
    summary = {"sampled": len(results), "clean": len(clean), "reproduced": sum(r["reproduced"] for r in results),
               "by_pdk": {p: f"{sum(1 for r in clean if r['pdk'] == p)}/{sum(1 for r in results if r['pdk'] == p)}"
                          for p in by_pdk},
               "failures": [r for r in results if r not in clean or not r["reproduced"]], "results": results}
    (run / "audit.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=1))


if __name__ == "__main__":
    main()
