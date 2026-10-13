# Walk one circuit through phases 1-4 of the netlist-in flow (run inside the iic-osic-tools container):
#
#   cd /foss/designs/glayout-martin
#   python glayout-work/demo_phases.py 1                  # read a netlist (AnalogGenie 157 = curated C08)
#   python glayout-work/demo_phases.py 2                  # annotate: structures, matched devices, blocks
#   python glayout-work/demo_phases.py 3                  # size, build, floorplan, route -> GDS + LVS netlist
#   python glayout-work/demo_phases.py 4                  # the graph the model will read
#   python glayout-work/demo_phases.py 3 --circuit ag2215_opamp --pdk sky130
#
# --circuit: a curated id (C01..C18, two_stage_ota) or an AnalogGenie key (ag157, ag2215_opamp, ...).
# Phases 5 and 6 have their own scripts under learn/ (see learn/README.md).
# Outputs go to glayout-work/out/demo/.
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "learn" / "external" / "AnalogGenie" / "Dataset"
OUT = ROOT / "glayout-work" / "out" / "demo"


def load(key: str):
    from glayout.schematic import curated, read_analoggenie, read_analoggenie_opamp
    cur = curated()
    if key in cur:
        return cur[key]
    if key.startswith("ag"):
        ag = key[2:].split("_")[0]
        return read_analoggenie_opamp(DATASET / ag) if key.endswith("_opamp") else read_analoggenie(DATASET / ag)
    sys.exit(f"unknown circuit {key!r}: use C01..C18, two_stage_ota or an AnalogGenie key like ag157")


def phase1(key: str, pdk_name: str) -> None:
    from glayout.schematic import read_analoggenie, textbook_schematic
    print("== Phase 1: read a netlist into a Schematic ==\n")
    print("AnalogGenie file:", DATASET / "157" / "157.cir")
    print((DATASET / "157" / "157.cir").read_text())
    ag = read_analoggenie(DATASET / "157")
    print(ag.summary(), "\nprovenance:", ag.provenance, "\nstructural problems:", ag.check() or "none")
    print("\nThe same circuit as PR #127's curated C08 (devices renamed):")
    print(textbook_schematic("C08").summary())
    if key not in ("C08", "ag157"):
        sch = load(key)
        print(f"\n--circuit {key}:\n{sch.summary(max_devices=12)}\nwarnings: {sch.warnings or 'none'}")


def phase2(key: str, pdk_name: str) -> None:
    from glayout.schematic import annotate
    print("== Phase 2: annotate (structures, matched devices, layout blocks) ==\n")
    sch = load(key)
    ann = annotate(sch)
    print(sch.summary(max_devices=12), "\n")
    print(ann.summary())
    print("\nstructures:", [(s.kind, s.devices) for s in ann.structures])
    if "matched" in sch.constraints:
        got = ann.matched_pairs()
        declared = [tuple(p) for p in sch.constraints["matched"]]
        print("PR #127 declared matched pairs:", declared,
              "-> all recovered" if all(frozenset(p) in got for p in declared) else "-> MISSING some")


def phase3(key: str, pdk_name: str) -> None:
    import glayout
    from glayout.schematic import schematic_routed
    print(f"== Phase 3: size, build blocks, floorplan, route on {pdk_name} ==\n")
    pdk = getattr(glayout, pdk_name)
    name = f"demo_{key.lower()}_{pdk_name}"
    comp, circuit, fp, rr, loop = schematic_routed(pdk, load(key), strict=False, return_result=True, name=name)
    print("\nsizing (synthetic, layout only):")
    for b, s in circuit.sizing.blocks.items():
        print(f"  {b:7s} unit {s.unit:5.1f} um  L {s.length:.2f} um  base fingers {s.base}  shapes x{s.splits}")
    print("\nfloorplan:", {k: round(v, 3) if isinstance(v, float) else v for k, v in fp.metrics.items()
                          if k in ("width", "height", "area", "dead_space", "hpwl")})
    print("routing:  ", rr.summary())
    print("closed loop rounds:", len(loop.rounds), " final DRR scales:", loop.scales)
    OUT.mkdir(parents=True, exist_ok=True)
    gds = OUT / f"{name}.gds"
    comp.write_gds(str(gds))
    (OUT / f"{name}.spice").write_text(comp.info["netlist"].generate_netlist())
    print(f"\nwrote {gds}\n  and {OUT / (name + '.spice')} (LVS reference)")
    print("open it with:  klayout", gds)


def phase4(key: str, pdk_name: str) -> None:
    import glayout
    from glayout.schematic import schematic_to_circuit, validate_graph
    print(f"== Phase 4: the heterogeneous graph (schema v1) on {pdk_name} ==\n")
    os.environ.setdefault("GLAYOUT_TABLES", "0")
    circuit = schematic_to_circuit(getattr(glayout, pdk_name), load(key))
    d = circuit.hetero_graph().to_dict()
    print("schema", d["schema_version"], "| level", d["meta"]["level"], "| problems:", validate_graph(d) or "none")
    for t, v in d["node_types"].items():
        print(f"  {t:10s} {len(v['names']):3d} nodes x {len(v['feature_names']):2d} features   e.g. {v['names'][:4]}")
    for t, v in d["edge_types"].items():
        print(f"  {t:28s} {len(v['index'][0]):3d} edges")
    dev = d["node_types"]["device"]
    print(f"\nnon-zero features of device {dev['names'][0]}:",
          {n: x for n, x in zip(dev["feature_names"], dev["x"][0]) if x})
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"graph_{key.lower()}_{pdk_name}.json"
    path.write_text(json.dumps(d, indent=1))
    print("wrote", path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Walk one circuit through phases 1-4")
    ap.add_argument("phase", type=int, choices=[1, 2, 3, 4])
    ap.add_argument("--circuit", default="C08")
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    args = ap.parse_args()
    os.environ.setdefault("GLAYOUT_TABLES_DEPTH", "1")      # top-level process tables only
    {1: phase1, 2: phase2, 3: phase3, 4: phase4}[args.phase](args.circuit, args.pdk)


if __name__ == "__main__":
    main()
