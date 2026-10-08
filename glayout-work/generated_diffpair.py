# This is form setting up gLayout
from pathlib import Path

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.blocks.elementary.diff_pair.diff_pair import diff_pair
from glayout.evaluation import write_lvs_netlist

OUT = Path(__file__).resolve().parent / "out" / Path(__file__).stem; OUT.mkdir(parents=True, exist_ok=True)

# Differential pair: two transistors in a 2x2 common-centroid layout (AB / BA) with shorted sources.
# Size it with width/fingers/length (it has no numcols); fingers must be 2 or more.
dp1 = diff_pair(
    pdk,
    width=3,           # um, per finger
    fingers=1,
    length=None,       # None = minimum length for the PDK
    n_or_p_fet=True,   # True = nfet, False = pfet
)
dp1.name = "diffpair_1"
dp1.write_gds(OUT / f"{dp1.name}.gds")
write_lvs_netlist(dp1, pdk, OUT / f"{dp1.name}.spice")    # KLayout's gf180 LVS finds it next to the GDS

dp2 = diff_pair(
    pdk,
    width=3,           # um, per finger
    fingers=2,
    length=None,       # None = minimum length for the PDK
    n_or_p_fet=True,   # True = nfet, False = pfet
)
dp2.name = "diffpair_2"
dp2.write_gds(OUT / f"{dp2.name}.gds")
write_lvs_netlist(dp2, pdk, OUT / f"{dp2.name}.spice")


# optional checks
print(dp1.name, pdk.drc_magic(dp1, dp1.name))
