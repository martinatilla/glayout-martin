# Route a 5-transistor OTA built from finger-sequence cells
import os
os.environ["GLAYOUT_NO_PIN_LABELS"] = "1"            # cells without their own labels; the routed top gets its own
os.environ.setdefault("GLAYOUT_TABLES_DEPTH", "1")   # only top-level process tables

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.cells.elementary.finger_sequence import cc_current_mirror, cc_diff_pair
from glayout.floorplan import Circuit, Instance, build_block
from glayout.floorplan.route_flow import closed_loop_floorplan, route_floorplan
from glayout.floorplan.router import RouterTech

# 1. blocks, each with one or more shape variants (same circuit, different finger split)
dp = build_block(pdk, "DP", "DP", cc_diff_pair, [dict(fingers=4, width=3.0), dict(fingers=2, width=6.0)])
load = build_block(pdk, "LOAD", "CM", cc_current_mirror, [dict(fingers=4, device="pfet")])
tail = build_block(pdk, "TAIL", "CM", cc_current_mirror, [dict(fingers=4, device="nfet")])

# 2. how the cells' pins connect (cell pin -> circuit net)
circuit = Circuit("ota5t", [
    Instance("DP", dp, {"VINP": "VINP", "VINN": "VINN", "VOUT1": "N1", "VOUT2": "VOUT", "VTAIL": "VTAIL", "B": "VSS"}),
    Instance("LOAD", load, {"VREF": "N1", "VOUT": "VOUT", "VSS": "VDD", "B": "VDD"}),
    Instance("TAIL", tail, {"VREF": "IBIAS", "VOUT": "VTAIL", "VSS": "VSS", "B": "VSS"}),
], self_symmetric=["DP", "LOAD"], ports=["VINP", "VINN", "VOUT", "IBIAS", "VDD", "VSS"])

# QUESTION: Could the graph this produces be visualized nicely?

# 3. floorplan with router feedback, then route and draw
tech = RouterTech.from_pdk(pdk)
loop = closed_loop_floorplan(pdk, circuit, [dp, load, tail], tech, seed=0)
ota, rr = route_floorplan(pdk, circuit, loop.floorplan, tech, name="ota5t_routed")

print(rr.summary())
ota.write_gds(f"{ota.name}.gds")
print(ota.info["netlist"].generate_netlist())
print(ota.name, pdk.drc_magic(ota, ota.name))