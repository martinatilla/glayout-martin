# This is form setting up gLayout

from glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
from glayout.blocks.elementary.current_mirror.current_mirror import current_mirror

# numcols=3 generates ABABAB, numcols=1 generates AB
for numcols in (3, 1):
    cm = current_mirror(pdk, numcols=numcols)   # add more parameters here, e.g. width=3, fingers=2
    cm.name = f"cmirror_{numcols}"
    cm.write_gds(f"{cm.name}.gds")

    # optional checks
    print(cm.name, pdk.drc_magic(cm, cm.name))
