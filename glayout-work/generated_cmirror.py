# This is for setting up gLayout
from pathlib import Path

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.cells.elementary.finger_sequence import cc_current_mirror
from glayout.evaluation import write_lvs_netlist

OUT = Path(__file__).resolve().parent / "out" / Path(__file__).stem; OUT.mkdir(parents=True, exist_ok=True)

# fingers=N puts N fingers on each device; the generator searches for the
# best common-centroid order (fingers=4 -> AABBBBAA, fingers=2 -> ABBA)
for fingers in (4, 2):
    cm = cc_current_mirror(pdk, fingers=fingers)   # also: device="pfet", width=3, ratio=2, sequence="A+ A- B+ B-"
    cm.name = f"cmirror_cc_{fingers}"
    cm.write_gds(OUT / f"{cm.name}.gds")
    write_lvs_netlist(cm, pdk, OUT / f"{cm.name}.spice")    # KLayout's gf180 LVS finds it next to the GDS

    # optional checks
    print(cm.name, cm.info["diagram"])
    print(cm.name, pdk.drc_magic(cm, cm.name))