# Benchmarks for the floorplanning framework (run inside the iic-osic-tools container):
#
#   cd /foss/designs/glayout-martin && .venv/bin/python glayout-work/framework_benchmark.py [--pdk gf180]
#
# 1. Current mirror: existing interdigitized `current_mirror` (ABAB, separate
#    diffusion per column) vs `cc_current_mirror` (common centroid, shared
#    diffusion), at the same device count and size (notes §2.8).
# 2. Floorplan of the two-stage OTA with and without DRR padding over several
#    seeds (the paper's Table 5 ablation).
# 3. Routing (the paper's Table 1 analogue): route every floorplan with the
#    inter-block A* router and compare no DRR, the paper's fixed DRR, and the
#    router-feedback closed loop (with and without the router in the annealer).
#    --skip-in-loop leaves out the slow in-loop variant.
#
# GLAYOUT_TABLES_DEPTH=1 keeps only the top-level tables. Results also go to
# glayout-work/results/framework_benchmark_<pdk>.json.
import argparse
import json
import os
import statistics
import time
from pathlib import Path

os.environ.setdefault("GLAYOUT_TABLES_DEPTH", "1")

from glayout.cells.elementary.current_mirror.current_mirror import current_mirror
from glayout.cells.elementary.finger_sequence import cc_current_mirror
from glayout.floorplan.examples import two_stage_ota_blocks, two_stage_ota_floorplan
from glayout.primitives.fet import multiplier
from glayout.util.comp_utils import evaluate_bbox
from glayout.placement.finger_sequence import DeviceSpec, FingerSequence
from glayout.util.process_table import ProcessTable, print_table

MIRROR = {"A": DeviceSpec("A", "VSS", "VREF", "VREF", 1), "B": DeviceSpec("B", "VSS", "VOUT", "VREF", 1)}


def interdigitized_model(n: int) -> FingerSequence:
    """ABAB... with one finger per column; columns never share diffusion."""
    devs = {k: DeviceSpec(d.name, d.source, d.drain, d.gate, n) for k, d in MIRROR.items()}
    return FingerSequence.from_compact(devs, " ".join(["A+ B+"] * n))


def column_pitch(pdk) -> float:
    """Column pitch of macro_two_transistor_interdigitized (its xdisp)."""
    col = multiplier(pdk, "n+s/d", width=3, fingers=1, dummy=False, sd_route_extension=0, gate_route_extension=0)
    return pdk.snap_to_2xgrid(evaluate_bbox(col)[0] + pdk.get_grule("active_diff")["min_separation"])


def bench_mirror(pdk, sizes=(2, 4)) -> list[dict]:
    rows = []
    pitch = column_pitch(pdk)   # ABAB: A and B centroids sit exactly one column apart
    with ProcessTable("Benchmark: current mirror", pdk.name) as pt:
        for n in sizes:
            with pt.stage(f"{n}+{n} fingers") as st:
                base = current_mirror(pdk, numcols=n, device="nfet")
                cc = cc_current_mirror(pdk, fingers=n, device="nfet")
                bm = interdigitized_model(n).metrics()
                seq = FingerSequence.from_compact(
                    {k: DeviceSpec(d.name, d.source, d.drain, d.gate, n) for k, d in MIRROR.items()},
                    cc.info["sequence"])
                cm = seq.metrics()
                for name, comp, m, s, cerr in (
                        ("current_mirror (ABAB)", base, bm, interdigitized_model(n).labels(), pitch),
                        ("cc_current_mirror", cc, cm, seq.labels(), cc.info["centroid_error_um"])):
                    rows.append({"fingers": f"{n}+{n}", "cell": name, "sequence": s,
                                 "w_um": round(comp.xsize, 2), "h_um": round(comp.ysize, 2),
                                 "area_um2": round(comp.xsize * comp.ysize, 1), "breaks": m.breaks,
                                 "centroid_err_um": round(cerr, 3),
                                 "drain_regions_per_finger": {k: round(v, 2) for k, v in m.drain_per_finger.items()}})
                st.detail(f"area {rows[-2]['area_um2']} → {rows[-1]['area_um2']} µm²")
    print_table(f"Current mirror comparison ({pdk.name})",
                ["fingers", "cell", "sequence", "size µm", "area µm²", "Δ area", "diff. breaks",
                 "centroid err µm", "drain regions / finger"],
                [(r["fingers"], r["cell"], r["sequence"], f"{r['w_um']}x{r['h_um']}", r["area_um2"],
                  "" if i % 2 == 0 else f"{r['area_um2'] / rows[i - 1]['area_um2'] - 1:+.1%}",
                  r["breaks"], r["centroid_err_um"],
                  " ".join(f"{k}={v}" for k, v in r["drain_regions_per_finger"].items()))
                 for i, r in enumerate(rows)],
                caption="drain regions / finger: 1.0 = every finger has its own drain diffusion; "
                        "0.5 = each drain region shared by two fingers (half the drain junction area)")
    return rows


def bench_floorplan(pdk, seeds=(0, 1, 2, 3, 4)) -> list[dict]:
    rows = []
    with ProcessTable("Benchmark: DRR ablation", f"{pdk.name}, seeds {list(seeds)}") as pt:
        with pt.stage("build blocks") as st:
            blocks = two_stage_ota_blocks(pdk)
            st.detail(f"{sum(len(b.variants) for b in blocks.values())} variants, reused for every run")
        for scale in (1.0, 0.0):
            with pt.stage(f"drr_scale={scale}") as st:
                for seed in seeds:
                    _, res = two_stage_ota_floorplan(pdk, seed=seed, drr_scale=scale, return_result=True,
                                                     blocks=blocks)
                    m = res.metrics
                    rows.append({"drr_scale": scale, "seed": seed, "dead_space": m["dead_space"],
                                 "hpwl_um": m["hpwl"], "area_um2": m["area"], "aspect": m["aspect"],
                                 "cost": m["cost"], "asym_um": m["asym_um"]})
                sel = [r for r in rows if r["drr_scale"] == scale]
                st.detail(f"dead space {statistics.mean(r['dead_space'] for r in sel):.1%}, "
                          f"HPWL {statistics.mean(r['hpwl_um'] for r in sel):.1f}µm (mean)")
    summary = []
    for scale in (1.0, 0.0):
        sel = [r for r in rows if r["drr_scale"] == scale]
        summary.append(("with DRR" if scale else "without DRR", len(sel),
                        f"{statistics.mean(r['dead_space'] for r in sel):.1%}",
                        f"{statistics.mean(r['hpwl_um'] for r in sel):.1f}",
                        f"{statistics.mean(r['area_um2'] for r in sel):.0f}",
                        f"{max(r['asym_um'] for r in sel):.3f}"))
    print_table(f"Two-stage OTA floorplan, DRR ablation ({pdk.name})",
                ["variant", "runs", "dead space", "HPWL µm", "area µm²", "max asym µm"], summary,
                caption="paper Table 5 (Infineon 130nm, different circuits): 57.4% / 797µm with DRR, "
                        "37.3% / 673µm without")
    return rows


def bench_routing(pdk, seeds=tuple(range(10)), in_loop_seeds=(0, 1, 2)) -> list[dict]:
    """Route the two-stage OTA floorplan per seed under four flows."""
    from glayout.floorplan.anneal import anneal_floorplan
    from glayout.floorplan.drr import apply_drr
    from glayout.floorplan.examples import two_stage_ota_circuit
    from glayout.floorplan.route_flow import closed_loop_floorplan, route_result
    from glayout.floorplan.router import RouterTech
    rows = []
    with ProcessTable("Benchmark: routing", f"{pdk.name}, seeds {list(seeds)}") as pt:
        with pt.stage("build blocks") as st:
            blocks = two_stage_ota_blocks(pdk, labels=False)
            circuit = two_stage_ota_circuit(blocks)
            tech = RouterTech.from_pdk(pdk)
            st.detail(f"router pitch {tech.pitch}µm on {'/'.join(tech.layers)}")
        flows = [("no DRR", seeds), ("DRR (paper)", seeds), ("closed loop", seeds),
                 ("closed loop + in-loop", in_loop_seeds)]
        for flow, fseeds in flows:
            with pt.stage(flow) as st:
                for seed in fseeds:
                    t0 = time.perf_counter()
                    rounds = 1
                    if flow in ("no DRR", "DRR (paper)"):
                        apply_drr(pdk, blocks.values(), scale=0.0 if flow == "no DRR" else 1.0, layers=tech.layers)
                        fp = anneal_floorplan(circuit, seed=seed)
                        rr = route_result(circuit, fp, tech)
                    else:
                        loop = closed_loop_floorplan(pdk, circuit, list(blocks.values()), tech, seed=seed,
                                                     in_loop=flow.endswith("in-loop"))
                        fp, rr, rounds = loop.floorplan, loop.routing, len(loop.rounds)
                    m = fp.metrics
                    rows.append({"flow": flow, "seed": seed, "routed": rr.success, "dead_space": m["dead_space"],
                                 "area_um2": m["area"], "hpwl_um": m["hpwl"], "wl_um": rr.wirelength,
                                 "vias": rr.vias, "rrr_iterations": rr.iterations, "rounds": rounds,
                                 "router_calls": m.get("router_calls", 0), "seconds": time.perf_counter() - t0})
                sel = [r for r in rows if r["flow"] == flow]
                st.detail(f"{sum(not r['routed'] for r in sel)}/{len(sel)} failed")
    summary = []
    for flow, _ in flows:
        sel = [r for r in rows if r["flow"] == flow]
        if not sel:
            continue
        ok = [r for r in sel if r["routed"]]
        mean = (lambda k: f"{statistics.mean(r[k] for r in ok):.1f}" if ok else "—")
        summary.append((flow, len(sel), f"{sum(not r['routed'] for r in sel) / len(sel):.0%}",
                        f"{statistics.mean(r['dead_space'] for r in sel):.1%}", mean("area_um2"), mean("hpwl_um"),
                        mean("wl_um"), mean("vias"), mean("rrr_iterations"),
                        f"{statistics.mean(r['seconds'] for r in sel):.1f}"))
    print_table(f"Two-stage OTA, routing by flow ({pdk.name})",
                ["flow", "runs", "failure rate", "dead space", "area µm²", "HPWL µm", "routed WL µm", "vias",
                 "RRR it.", "s / run"], summary,
                caption="area/HPWL/WL/vias/iterations: mean over routed runs. Paper Table 1 (failure rate): "
                        "routing-aware 9.6%, R-GCN RL 0-shot 79.0%")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    ap.add_argument("--skip-in-loop", action="store_true")
    args = ap.parse_args()
    if args.pdk == "gf180":
        from glayout import gf180 as pdk
    else:
        from glayout import sky130 as pdk
    out = {"mirror": bench_mirror(pdk), "floorplan": bench_floorplan(pdk),
           "routing": bench_routing(pdk, in_loop_seeds=() if args.skip_in_loop else (0, 1, 2))}
    path = Path(__file__).resolve().parent / "results" / f"framework_benchmark_{args.pdk}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path}")
