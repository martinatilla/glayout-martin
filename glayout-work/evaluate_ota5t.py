# Post-layout evaluation of the routed 5T OTA (gf180), inside the iic-osic-tools container:
#
#   cd /foss/designs/glayout-martin && .venv/bin/python glayout-work/evaluate_ota5t.py [--seed 0]
#
# klayout, kpex and ngspice must be on PATH and PDK_ROOT set (a login shell in the
# container has them; through `docker exec ... bash -c`, first
# `export PATH=/foss/tools/klayout:/foss/tools/bin:$PATH PDK_ROOT=/foss/pdks; unset PYTHONPATH`,
# since the login PYTHONPATH points the 3.10 venv at python3.12 packages).
#
# Builds the OTA as simple_ota.py does, then glayout.evaluation.evaluate: LVS, kpex
# extraction, and one open-loop testbench on the schematic, the extracted devices and
# the extracted devices + capacitance. Intermediate files (LVS, kpex, DUT netlists, decks,
# rawfiles) go to --workdir, default glayout-work/out/evaluate_ota5t/ (gitignored); the
# summary to glayout-work/results/evaluate_ota5t_gf180.json.
import argparse
import json
import os
from pathlib import Path

os.environ["GLAYOUT_NO_PIN_LABELS"] = "1"            # cells without their own labels; the routed top gets its own
os.environ.setdefault("GLAYOUT_TABLES_DEPTH", "1")   # only top-level process tables

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.cells.elementary.finger_sequence import cc_current_mirror, cc_diff_pair
from glayout.evaluation import OtaTestbench, evaluate
from glayout.floorplan import Circuit, Instance, build_block
from glayout.floorplan.route_flow import closed_loop_floorplan, route_floorplan
from glayout.floorplan.router import RouterTech


def build_ota5t(pdk, seed: int = 0):
    dp = build_block(pdk, "DP", "DP", cc_diff_pair, [dict(fingers=4, width=3.0), dict(fingers=2, width=6.0)])
    load = build_block(pdk, "LOAD", "CM", cc_current_mirror, [dict(fingers=4, device="pfet")])
    tail = build_block(pdk, "TAIL", "CM", cc_current_mirror, [dict(fingers=4, device="nfet")])
    circuit = Circuit("ota5t", [
        Instance("DP", dp, {"VINP": "VINP", "VINN": "VINN", "VOUT1": "N1", "VOUT2": "VOUT", "VTAIL": "VTAIL", "B": "VSS"}),
        Instance("LOAD", load, {"VREF": "N1", "VOUT": "VOUT", "VSS": "VDD", "B": "VDD"}),
        Instance("TAIL", tail, {"VREF": "IBIAS", "VOUT": "VTAIL", "VSS": "VSS", "B": "VSS"}),
    ], self_symmetric=["DP", "LOAD"], ports=["VINP", "VINN", "VOUT", "IBIAS", "VDD", "VSS"])
    tech = RouterTech.from_pdk(pdk)
    loop = closed_loop_floorplan(pdk, circuit, [dp, load, tail], tech, seed=seed)
    ota, rr = route_floorplan(pdk, circuit, loop.floorplan, tech, name="ota5t_routed")
    if not rr.success:
        raise RuntimeError(f"routing failed: {rr.summary()}")
    return ota


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ibias", type=float, default=20e-6, help="A, into IBIAS (the tail mirror's diode)")
    ap.add_argument("--cl", type=float, default=1e-12, help="F, load on VOUT")
    ap.add_argument("--corner", default="typical")
    ap.add_argument("--workdir", default=str(Path(__file__).resolve().parent / "out" / Path(__file__).stem))
    args = ap.parse_args()

    ota = build_ota5t(pdk, seed=args.seed)
    ev = evaluate(ota, OtaTestbench(ibias=args.ibias, cl=args.cl, corner=args.corner), pdk, workdir=args.workdir)
    path = Path(__file__).resolve().parent / "results" / "evaluate_ota5t_gf180.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"seed": args.seed, **ev.to_dict()}, indent=2))
    print(f"wrote {path}")
