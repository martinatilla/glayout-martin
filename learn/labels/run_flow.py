"""Label job: run the floorplan + route flow on the v1 circuits and record what it produced.

Run inside the iic-osic-tools container (it builds layout cells):

    cd /foss/designs/glayout-martin
    .venv/bin/python learn/labels/run_flow.py --run pilot --pilot                 # test set + 100 train circuits
    .venv/bin/python learn/labels/run_flow.py --run full --sizings 3 --seeds 2    # every v1 circuit

For every (circuit, PDK, sizing seed) the circuit is annotated, sized and built
(``glayout.schematic``), and its graph (schema v1) is written *before* any
floorplanning. Then, per seed, ``closed_loop_floorplan`` (annealer + A* router
with padding grown where routing fails) runs and one record is written:

  graph targets   area, dead space, HPWL, width, height, routed, rounds, wirelength, vias, RRR iterations,
                  failed nets, unreachable pins, and the same for the first round (no padding)
  block targets   final DRR scale, chosen variant, mirrored
  net targets     failed in the first round, routed wirelength

Failures are records too (``status: error`` with a class and the stage), never dropped.
The job is resumable: records and graphs already in the output are skipped.

Output: learn/labels/out/<run>/{records.jsonl, graphs.jsonl, run.json}
"""
from __future__ import annotations

import argparse
import datetime
import json
import multiprocessing as mp
import os
import random
import subprocess
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

LEARN = Path(__file__).resolve().parents[1]
ROOT = LEARN.parent
OUT = LEARN / "labels" / "out"
SCHEMATICS = LEARN / "data" / "build" / "schematics.jsonl"
SPLITS = LEARN / "data" / "splits.json"
FLOW = {"mode": "closed_loop", "start_scale": 0.0, "step": 0.25, "max_scale": 2.0, "rounds": 10, "in_loop": False}


def git_state(path: Path) -> dict:
    def run(*a):
        return subprocess.run(["git", "-C", str(path), *a], capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


# ---- worker -------------------------------------------------------------------
_PDKS = {}


def _pdk(name: str):
    if name not in _PDKS:
        from glayout import gf180, sky130
        _PDKS.update({"gf180": gf180, "sky130": sky130})
    return _PDKS[name]


def _error(stage: str, e: BaseException) -> dict:
    return {"stage": stage, "class": type(e).__name__, "code": getattr(e, "code", None), "message": str(e)[:400],
            "trace": traceback.format_exc().splitlines()[-3:]}


def _targets(circuit, loop) -> dict:
    from glayout.floorplan.router import _path_wire
    fp, rr = loop.floorplan, loop.routing
    m = fp.metrics
    r0 = loop.rounds[0]
    unreachable_nets0 = {circuit[o.split(".", 1)[0]].nets[o.split(".", 1)[1]] for o in r0["unreachable"]}
    failed0 = set(r0["failed"]) | unreachable_nets0
    nets = {}
    for net in circuit.net_pins(min_pins=1):
        wl = _path_wire(rr.grid, rr.paths[net]) if net in rr.paths else None
        nets[net] = {"failed_round0": net in failed0, "wirelength_um": None if wl is None else round(wl, 3)}
    return {
        "graph": {
            "area_um2": round(m["area"], 4), "dead_space": round(m["dead_space"], 6), "hpwl_um": round(m["hpwl"], 4),
            "width_um": round(m["width"], 4), "height_um": round(m["height"], 4), "aspect": round(m["aspect"], 6),
            "asym_um": round(m["asym_um"], 4), "sum_block_area_um2": round(m["sum_block_area"], 4),
            "routed": rr.success, "rounds": len(loop.rounds), "wirelength_um": round(rr.wirelength, 3),
            "vias": rr.vias, "rrr_iterations": rr.iterations, "failed_nets": len(rr.failed_nets),
            "unreachable_pins": len(rr.unreachable),
            "routed_round0": r0["routed"], "dead_space_round0": round(r0["dead_space"], 6),
            "area_round0_um2": round(r0["area"], 4), "hpwl_round0_um": round(r0["hpwl"], 4),
        },
        "block": {inst.name: {"drr_scale": loop.scales[inst.name], "variant": fp.placed[inst.name].variant,
                              "mirrored": fp.placed[inst.name].mirrored} for inst in circuit.instances},
        "net": nets,
    }


def run_task(task: dict) -> dict:
    """One circuit on one PDK: every sizing seed, every flow seed."""
    os.environ["GLAYOUT_TABLES"] = "0"
    from glayout.floorplan.route_flow import closed_loop_floorplan
    from glayout.floorplan.router import RouterTech
    from glayout.schematic import Schematic, annotate, curated, pdk_limits, schematic_to_circuit, size_schematic
    from glayout.schematic import to_circuit
    to_circuit.BLOCK_CACHE.clear()          # cells are rarely shared across circuits; keep memory flat
    key, pdk_name = task["key"], task["pdk"]
    pdk = _pdk(pdk_name)
    base = {"key": key, "split": task["split"], "pdk": pdk_name, "meta": task["meta"]}
    records, graphs = [], []
    sch = curated()[key] if task["schematic"] is None else Schematic.from_json(task["schematic"])
    for k in task["sizing_seeds"]:
        graph_id = f"{key}|{pdk_name}|s{k}"
        t0 = time.time()
        try:
            ann = annotate(sch)
            sizing = size_schematic(sch, ann, **pdk_limits(pdk), seed=k)
            circuit = schematic_to_circuit(pdk, sch, ann, sizing, labels=False)
            graph = circuit.hetero_graph().to_dict()
            tech = RouterTech.from_pdk(pdk)
        except Exception as e:
            for seed in task["seeds"]:
                records.append({**base, "id": f"{graph_id}|r{seed}", "graph_id": None, "sizing_seed": k, "seed": seed,
                                "status": "error", "error": _error("build", e), "timing": {"build_s": time.time() - t0}})
            continue
        build_s = round(time.time() - t0, 2)
        if graph_id not in task["done_graphs"]:
            graphs.append({"graph_id": graph_id, "key": key, "pdk": pdk_name, "sizing_seed": k,
                           "sizing": sizing.to_json(), "build_s": build_s, "graph": graph})
        blocks = [inst.block for inst in circuit.instances]
        for seed in task["seeds"]:
            rid = f"{graph_id}|r{seed}"
            if rid in task["done_records"]:
                continue
            t1 = time.time()
            rec = {**base, "id": rid, "graph_id": graph_id, "sizing_seed": k, "seed": seed}
            try:
                loop = closed_loop_floorplan(pdk, circuit, blocks, tech, seed=seed, start_scale=FLOW["start_scale"],
                                             step=FLOW["step"], max_scale=FLOW["max_scale"], rounds=FLOW["rounds"],
                                             in_loop=FLOW["in_loop"])
                rec.update({"status": "ok", "targets": _targets(circuit, loop)})
            except Exception as e:
                rec.update({"status": "error", "error": _error("flow", e)})
            rec["timing"] = {"build_s": build_s, "flow_s": round(time.time() - t1, 2)}
            records.append(rec)
    return {"records": records, "graphs": graphs}


# ---- driver -------------------------------------------------------------------
def select_items(splits: dict, wanted: set[str], pilot: int, keys: list[str]) -> list[tuple[str, str]]:
    v1 = {k: it for k, it in splits["items"].items() if it["layout_v1"] == "ok" and it["split"] in wanted}
    if keys:
        return [(k, v1[k]["split"]) for k in keys if k in v1]
    out = sorted((k, it["split"]) for k, it in v1.items() if it["split"] != "train")
    train = sorted(k for k, it in v1.items() if it["split"] == "train")
    if pilot:
        random.Random(0).shuffle(train)
        train = sorted(train[:pilot])
    return out + [(k, "train") for k in train]


def load_done(path: Path, field: str) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)[field] for line in path.open() if line.strip()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, help="output folder name under learn/labels/out")
    ap.add_argument("--pdks", default="gf180,sky130")
    ap.add_argument("--splits", default="train,val,test")
    ap.add_argument("--sizings", type=int, default=1, help="sizing seeds 0..N-1")
    ap.add_argument("--seeds", type=int, default=1, help="flow seeds 0..N-1")
    ap.add_argument("--pilot", nargs="?", type=int, const=100, default=0,
                    help="val + test, and this many train circuits (seeded sample)")
    ap.add_argument("--keys", default="", help="comma-separated item keys (overrides the selection)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--tasks-per-child", type=int, default=10)
    args = ap.parse_args()

    out = OUT / args.run
    out.mkdir(parents=True, exist_ok=True)
    splits = json.loads(SPLITS.read_text())
    items = select_items(splits, set(args.splits.split(",")), args.pilot, [k for k in args.keys.split(",") if k])
    schematics = {}
    with SCHEMATICS.open() as f:
        for line in f:
            r = json.loads(line)
            schematics[r["key"]] = r["schematic"]
    meta = {"glayout": git_state(ROOT / "gLayout"), "learn": git_state(ROOT), "flow": FLOW,
            "graph_schema": None, "sizing": "glayout.schematic.sizing (synthetic, layout only)"}
    from glayout.schematic.graph import SCHEMA_VERSION
    meta["graph_schema"] = SCHEMA_VERSION
    done_r, done_g = load_done(out / "records.jsonl", "id"), load_done(out / "graphs.jsonl", "graph_id")
    pdks = args.pdks.split(",")
    tasks = [{"key": k, "split": s, "pdk": p, "schematic": None if splits["items"][k]["source"] == "curated"
              else schematics[k], "sizing_seeds": list(range(args.sizings)), "seeds": list(range(args.seeds)),
              "done_records": {f"{k}|{p}|s{z}|r{r}" for z in range(args.sizings) for r in range(args.seeds)} & done_r,
              "done_graphs": {f"{k}|{p}|s{z}" for z in range(args.sizings)} & done_g, "meta": meta}
             for k, s in items for p in pdks]
    tasks = [t for t in tasks if len(t["done_records"]) < args.sizings * args.seeds]
    run_json = out / "run.json"
    info = json.loads(run_json.read_text()) if run_json.exists() else {"started": datetime.datetime.now().isoformat()}
    info.update({"args": vars(args), "meta": meta, "items": len(items), "pending_tasks": len(tasks)})
    run_json.write_text(json.dumps(info, indent=1))
    print(f"{len(items)} circuits x {len(pdks)} PDKs: {len(tasks)} tasks pending, {len(done_r)} records already done")
    t0, n_rec, status = time.time(), 0, Counter()
    with mp.get_context("fork").Pool(args.jobs, maxtasksperchild=args.tasks_per_child) as pool, \
            (out / "records.jsonl").open("a") as rf, (out / "graphs.jsonl").open("a") as gf:
        for i, res in enumerate(pool.imap_unordered(run_task, tasks), 1):
            for g in res["graphs"]:
                gf.write(json.dumps(g, sort_keys=True) + "\n")
            for r in res["records"]:
                rf.write(json.dumps(r, sort_keys=True) + "\n")
                n_rec += 1
                status[r["status"] if r["status"] == "error" else
                       ("routed" if r["targets"]["graph"]["routed"] else "unrouted")] += 1
            rf.flush()
            gf.flush()
            if i % 10 == 0 or i == len(tasks):
                el = time.time() - t0
                print(f"[{i}/{len(tasks)}] {n_rec} records {dict(status)} {el:.0f}s "
                      f"({el / i:.1f}s/task, ETA {el / i * (len(tasks) - i) / 60:.0f} min)", flush=True)
    info.update({"finished": datetime.datetime.now().isoformat(), "seconds": round(time.time() - t0, 1),
                 "new_records": n_rec, "status": dict(status)})
    run_json.write_text(json.dumps(info, indent=1))


if __name__ == "__main__":
    sys.exit(main())
