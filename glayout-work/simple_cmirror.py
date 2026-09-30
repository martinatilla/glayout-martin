"""simple_cmirror.py - a 1:1 NMOS current mirror built by hand with gLayout (sky130)."""
from glayout import (sky130, nmos, tapring, c_route, L_route, straight_route, align_comp_to_port,
                     evaluate_bbox, movey, rename_ports_by_orientation, Netlist)
from glayout.backend import Component, rectangle


def cmirror_netlist(fet_netlist: Netlist) -> Netlist:
    """Reference schematic: M1 (diode) and M2 (mirror) share gate, source and bulk."""
    nl = Netlist(circuit_name="SIMPLE_CMIRROR", nodes=["VREF", "VOUT", "VSS", "B"])
    # the nmos primitive's subckt pins are D G S B DUM (DUM = its dummy devices)
    nl.connect_netlist(fet_netlist, [("D", "VREF"), ("G", "VREF"), ("S", "VSS"), ("B", "B"), ("DUM", "B")])
    nl.connect_netlist(fet_netlist, [("D", "VOUT"), ("G", "VREF"), ("S", "VSS"), ("B", "B"), ("DUM", "B")])
    return nl


def simple_cmirror(pdk=sky130, width: float = 3.0, length: float = 0.5, fingers: int = 2) -> Component:
    # 1. PRIMITIVES -- one parameterized FET, instanced twice
    fet = nmos(pdk, width=width, length=length, fingers=fingers,
               with_tie=False, with_substrate_tap=False, with_dnwell=False)

    top = Component("simple_cmirror")
    ref = top << fet   # M1: reference, diode-connected
    mir = top << fet   # M2: mirror output

    # 2. PLACEMENT -- stack vertically, spacing derived from the PDK's rules
    sep = pdk.util_max_metal_seperation()
    _, h = evaluate_bbox(fet)
    movey(ref, +(h / 2 + sep))
    movey(mir, -(h / 2 + sep))

    # 3. ROUTING -- push the vertical trunks just outside the FETs' bounding box
    gate_W = ref.ports["multiplier_0_gate_W"]
    src_E = ref.ports["multiplier_0_source_E"]
    gate = top << c_route(pdk, gate_W, mir.ports["multiplier_0_gate_W"],
                          extension=(gate_W.center[0] - ref.xmin) + sep)
    top << c_route(pdk, src_E, mir.ports["multiplier_0_source_E"],
                   extension=(ref.xmax - src_E.center[0]) + sep)
    top << L_route(pdk, ref.ports["multiplier_0_drain_W"], gate.ports["con_N"])  # diode connection

    # 4. SUBSTRATE TIE RING (bulk), then tie the dummy devices to it
    tap_sep = max(sep, pdk.get_grule("active_diff", "active_tap")["min_separation"])
    tap_sep += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]
    w, h_all = evaluate_bbox(top)
    ring = top << tapring(pdk, enclosed_rectangle=(w + 2 * tap_sep, h_all + 2 * tap_sep),
                          sdlayer="p+s/d", horizontal_glayer="met2", vertical_glayer="met1")
    for dev in (ref, mir):
        top << straight_route(pdk, dev.ports["multiplier_0_dummy_L_gsdcon_top_met_W"],
                              ring.ports["W_top_met_W"], glayer2="met1")
        top << straight_route(pdk, dev.ports["multiplier_0_dummy_R_gsdcon_top_met_E"],
                              ring.ports["E_top_met_E"], glayer2="met1")

    # 5. PORTS + NETLIST -- expose ports hierarchically, attach reference netlist
    top.add_ports(ref.get_ports_list(), prefix="ref_")
    top.add_ports(mir.get_ports_list(), prefix="mir_")
    top.add_ports(ring.get_ports_list(), prefix="tie_")
    top.info["netlist"] = cmirror_netlist(fet.info["netlist"])
    top = rename_ports_by_orientation(top)

    # 6. PIN LABELS -- so LVS can match layout nets to the netlist's pins
    for text, port in [("VREF", "ref_multiplier_0_drain_W"), ("VOUT", "mir_multiplier_0_drain_W"),
                       ("VSS", "ref_multiplier_0_source_E"), ("B", "tie_W_top_met_W")]:
        met = pdk.layer_to_glayer(top.ports[port].layer)          # e.g. "met1"
        pin = rectangle(layer=pdk.get_glayer(f"{met}_pin"), size=(0.27, 0.27), centered=True).copy()
        pin.add_label(text=text, layer=pdk.get_glayer(f"{met}_label"))
        top.add(align_comp_to_port(pin, top.ports[port], alignment=("c", "c")))  # centered ON the metal
    return top


if __name__ == "__main__":
    cm = simple_cmirror(sky130)
    cm.write_gds("simple_cmirror.gds")
    print(cm.info["netlist"].generate_netlist())
    print("size (um):", evaluate_bbox(cm))