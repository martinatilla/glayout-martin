# Current mirror: shared gate rail + provenance tool

> **Superseded (2026-10-06):** `shared_gate` is now one case of net-aware rails in the interdigitized macro, which
> also merges shared source rails, removes every remaining short (`current_mirror`, `opamp`, `diff_pair_cmirrorbias`,
> `smart_route`) and compacts the rail pitch. See `floorplanning-framework-changes.md` §7. The provenance tool
> (§3 below) is unchanged.

Reference notes for the uncommitted changes in the `gLayout` submodule (branch `fixing_cmirror`).
Paths below are relative to this folder.

| # | File | What changed |
|---|------|--------------|
| 1 | [two_transistor_interdigitized.py](gLayout/src/glayout/placement/two_transistor_interdigitized.py) | New `shared_gate` option: one gate rail for A and B |
| 2 | [current_mirror.py](gLayout/src/glayout/cells/elementary/current_mirror/current_mirror.py) | Uses `shared_gate=True`; gate-short route removed |
| 3 | [provenance.py](gLayout/src/glayout/util/provenance.py) (new) | Debug tool: trace a shape in the GDS back to the code that drew it |
| 4 | [backend/\_\_init\_\_.py](gLayout/src/glayout/backend/__init__.py) | 3 lines: turn the tool on with `GLAYOUT_PROVENANCE=1` |
| 5 | [glayout-work/generated_cmirror.py](glayout-work/generated_cmirror.py) | Builds `cmirror_3` and `cmirror_1` in one run |

---

## 1. Why: the current mirror had two gate rails that were then shorted together

`current_mirror()` is built on `macro_two_transistor_interdigitized`, a **generic** placement.
It puts the two transistors in an `A B A B …` row and assumes A and B have **independent**
gate, source and drain nets, as a differential pair does. To keep the nets apart, every B device
is built with its routing rails pushed further out, so each terminal gets its own horizontal
metal2 track:

```
BEFORE (6 tracks)                    AFTER (5 tracks)
 ── B drain   VOUT                    ── B drain   VOUT
 ── B source  VSS  ┐ C route          ── B source  VSS  ┐ C route (unchanged)
 ── A drain   VREF │                  ── A drain   VREF │
 ── A source  VSS  ┘                  ── A source  VSS  ┘
 [A][B][A][B][A][B]                   [A][B][A][B][A][B]
 ── A gate    G    ┐ C route          ── A+B gate  G     (one rail)
 ── B gate    G    ┘
```

In a current mirror the two gates are **the same net**. So the old code drew two gate rails,
about 1.1 µm apart, only to short them with a C route (`c_route(A_gate_W, B_gate_W)`) plus an
L route for the diode connection. That cost area, added a via2/metal3 stack, and used
extra poly stubs to make A's gate as long as B's.

This was found by clicking the two gate arms in KLayout and tracing them with the provenance
tool (section 3).

---

## 2. What changed

### 2a. `macro_two_transistor_interdigitized`: new `shared_gate` option

[two_transistor_interdigitized.py:122](gLayout/src/glayout/placement/two_transistor_interdigitized.py:122)

`shared_gate: bool = False`. **The default keeps the old behaviour**, so every existing caller
gets the same layout as before. With `shared_gate=True`:

| Where | Change | Why |
|---|---|---|
| [line 159](gLayout/src/glayout/placement/two_transistor_interdigitized.py:159) | B gets `gate_route_extension = 0`, the same as A | B's gate vias land at A's height, on one shared rail |
| [line 187](gLayout/src/glayout/placement/two_transistor_interdigitized.py:187) | The poly stubs that lengthened A's gates are skipped | With one rail, A and B gate poly already have equal length |
| [line 198](gLayout/src/glayout/placement/two_transistor_interdigitized.py:198) | `B_gate = A_gate`: no second gate bus is drawn | The `B_gate_*` ports become aliases of `A_gate_*`, so code reading them still works |

Why this is always safe in this macro: everything that rises from a device is vertical (met1
for source/drain, poly for gates), and every rail is horizontal met2. A stub crosses the other
rails on a different layer and only connects where it has a via, so moving B's gate vias onto
A's rail can't short to anything else.

### 2b. The netlist matches the layout

[two_transistor_interdigitized.py:66](gLayout/src/glayout/placement/two_transistor_interdigitized.py:66). `two_tran_interdigitized_netlist(..., shared_gate=False)`:
with `True`, device `XB` uses `VG1` and the subcircuit has no `VG2` pin
([lines 99–111](gLayout/src/glayout/placement/two_transistor_interdigitized.py:99)).
`two_nfet_interdigitized` and `two_pfet_interdigitized` pass the flag through
([lines 292](gLayout/src/glayout/placement/two_transistor_interdigitized.py:292) and [378](gLayout/src/glayout/placement/two_transistor_interdigitized.py:378)).
**Why:** a standalone shared-gate row has one gate net in the layout, so its reference netlist
must too, or LVS would fail.

### 2c. `current_mirror()` uses it

[current_mirror.py:147, 157](gLayout/src/glayout/cells/elementary/current_mirror/current_mirror.py:147): `shared_gate=True` for both the nfet and the pfet branch.

[current_mirror.py:164–165](gLayout/src/glayout/cells/elementary/current_mirror/current_mirror.py:164):

```python
# before
gate_short = interdigitized_fets << c_route(pdk, ...ports['A_gate_W'], ...ports['B_gate_W'], extension=3*maxmet_sep, viaoffset=False)
interdigitized_fets << L_route(pdk, ...ports['A_drain_W'], gate_short.ports['con_N'], viaoffset=False, fullbottom=False)

# after
interdigitized_fets << c_route(pdk, ...ports['A_drain_W'], ...ports['A_gate_W'], extension=3*maxmet_sep, viaoffset=False)
```

The gate short is no longer needed. The diode connection (reference drain to gate) is now **one** C
route from A's drain rail to the shared gate rail, where before it was a C route plus an L route.
The source short (line 163) is unchanged. The netlist for `CMIRROR` is unchanged too: it
already tied both gates to `VREF`.

### 2d. What was left alone on purpose

- **`opamp.py` and `diff_pair_cmirrorbias.py`** build mirrors straight from
  `two_nfet_interdigitized` and short the gates with their own C route. They don't pass
  `shared_gate`, so their layout is byte-identical to before. They could adopt it later.
- **Diff pairs, `four_transistor_interdigitized` and `smart_route`** need separate gates, so they
  keep the default.
- **`add_two_int_labels`** (not called anywhere) would put `VG1` and `VG2` labels on the same rail
  if used on a shared-gate row.
- **Shared source rail:** the same idea would work for VSS, but it isn't done yet.

---

## 3. Provenance tool (debug only)

[util/provenance.py](gLayout/src/glayout/util/provenance.py) + [backend/\_\_init\_\_.py:76–78](gLayout/src/glayout/backend/__init__.py:76)

**Why:** most generators flatten what they return (routes, via stacks, and on gf180 the finished
cell), so KLayout's cell tree can't tell you which Python code drew a shape.

**How it works:** when enabled, every `Component` records the call chain that created it. When
it is placed into a parent, it gets a text label on layer **255/0**
(`"<w>x<h> | function file:line < caller < …"`). Labels move with the geometry and survive
`flatten()`. It is off unless the environment variable is set, and it changes no polygons: this
was checked on the current mirror, where all 923 polygons, the pin labels and the bounding box
were identical with and without it.

```bash
GLAYOUT_PROVENANCE=1 python generated_cmirror.py          # build with tags
python -m glayout.util.provenance cmirror_3.gds -6.63 -4.31   # what drew this point?
```

Results are sorted smallest first, and the first entry is usually the culprit. You can also switch on
layer 255/0 in KLayout and hover over the labels.

Things to know:
- **Don't run DRC or LVS on a tagged GDS.** Layer 255 isn't in the PDK.
- **Some results appear twice** (e.g. `straight_route.py:79` and `:109`): that's the route before and after its internal flatten.
- **Reused cells show their first creator.** Cells cached by `@cell` carry the call chain of whoever created them first.
- **Shapes drawn straight onto the top cell have no tag**, e.g. the pwell from `add_padding`.

---

## 4. Results and checks

**Size (bounding box):** the width is unchanged; the height drops by about 1.1 µm.

| PDK | Device | Before | After |
|---|---|---|---|
| gf180 | nfet / pfet | 11.62 µm | **10.52 µm** (−9.5%) |
| sky130 | nfet | 10.41 µm | **9.27 µm** |
| sky130 | pfet | 10.51 µm | **9.37 µm** |

In `cmirror_3` (gf180), the gate contacts went from **two rows of 3** to **one row of 6**, and the
polygon count went from 923 to 900.

**DRC / LVS:** nfet and pfet, `numcols` 1, 2 and 3, gf180 and sky130 (12 cases). All pass
klayout DRC, magic DRC and LVS, before and after the change.

**Other cells unchanged:** built with the default `shared_gate=False`, the geometry is
byte-identical before and after for `two_nfet_interdigitized`, `two_pfet_interdigitized`,
`generic_4T_interdigitzed`, `diff_pair_ibias` and `opamp`. Both backends (gdsfactory and gdstk)
build the new mirror.

**Your files:** `glayout-work/reference/cmirror_1.gds` (new) vs `cmirror_1_old.gds` (before); the
`cmirror_3` pair is only in git history (`9ec41c0`). The new files were built with
`glayout-martin/.venv` and match the verified layouts.

---

## 5. Known open items

| Item | Where | Notes |
|---|---|---|
| Zero-width metal3 slivers (4 per mirror) | [c_route.py:262](gLayout/src/glayout/routing/c_route.py:262) | The fix-up loop draws a zero-length `straight_route` when the via already sits flush with the bar. Planned as a separate routing change: skip degenerate segments, and fall back to `straight_route` when the ports line up. |
| `n_block` / `super_class_AB_OTA` don't build | `cells/composite/fvf_based_ota/` | `AttributeError: 'str' object has no attribute 'nodes'` in their netlist code. **The error predates this change.** These cells use `current_mirror`, so their geometry changes but couldn't be checked. |
| Layout tests not run | `tests/test_cells_layout.py` | pytest isn't installed in the venv. DRC/LVS and direct builds covered the same cells. |
| Nothing committed | submodule + outer repo | Commit inside `gLayout` on `fixing_cmirror`, then commit the new submodule pointer in `glayout-martin`. |

## 6. Reproducing the checks

Run inside the iic-osic-tools container, with the EDA tools on `PATH`:

```bash
export PATH=/foss/tools/klayout:/foss/tools/magic/bin:/foss/tools/netgen/bin:$PATH
cd /foss/designs/glayout-martin/gLayout
python tests/drc/run_cell_drc.py --pdk gf180 --cells current_mirror_nfet,current_mirror_pfet --engine both --out-dir /tmp/drc_gf180
python tests/lvs/run_cell_lvs.py --pdk gf180 --inputs-dir /tmp/drc_gf180 --out-dir /tmp/lvs_gf180
```

Use `--params <csv>` to set `numcols`. The default CSV in `tests/parameters/` uses `numcols=2`.
