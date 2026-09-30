# This is form setting up gLayout

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.blocks.elementary.diff_pair.diff_pair import diff_pair

# This generates ABABAB in cmirror_3
dp = diff_pair(pdk)       # add parameters here, e.g. numcols=3
dp.name = "diffpair"
dp.write_gds("diffpair.gds")


print(pdk.drc_magic(dp, dp.name))