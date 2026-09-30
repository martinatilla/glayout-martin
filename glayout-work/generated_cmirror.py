# This is form setting up gLayout

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.blocks.elementary.current_mirror.current_mirror import current_mirror

# This generates ABABAB in cmirror_3
cm = current_mirror(pdk)       # add parameters here, e.g. numcols=3
cm.name = "cmirror_3"
cm.write_gds("cmirror_3.gds")

# This generates AB
# cm = current_mirror(pdk, numcols=1)       # add parameters here, e.g. numcols=3
# cm.name = "cmirror_1"
# cm.write_gds("cmirror_1.gds")

# optional checks
print(pdk.drc_magic(cm, cm.name))