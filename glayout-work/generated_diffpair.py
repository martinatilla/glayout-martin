# This is form setting up gLayout

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.blocks.elementary.diff_pair.diff_pair import diff_pair

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
dp1.write_gds(f"{dp1.name}.gds")

dp2 = diff_pair(
    pdk,
    width=3,           # um, per finger
    fingers=2,
    length=None,       # None = minimum length for the PDK
    n_or_p_fet=True,   # True = nfet, False = pfet
)
dp2.name = "diffpair_2"
dp2.write_gds(f"{dp2.name}.gds")


# optional checks
print(dp1.name, pdk.drc_magic(dp1, dp1.name))
