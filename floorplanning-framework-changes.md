# Routing-aware floorplanning framework: change log

Implementation notes for bringing the routing-aware floorplanning method (Basso et al., NeurIPS 2025 MLSys
workshop, arXiv:2510.15387) and the common-centroid / shared-diffusion proposal from
`routing_aware_floorplanning_notes.md` into gLayout. All code changes are in the `gLayout` submodule
(branch `my-new-feature`) and are **uncommitted**. Paths below are relative to this folder.

## Status by phase

| Phase | What | Status |
|---|---|---|
| 1 | Finger-sequence generator: common centroid + diffusion shared *across* devices (Level 0) | **Done.** DRC (klayout + magic) and LVS clean on gf180 and sky130 |
| 2 | Block abstraction: shape variants, pins with sides | **Done** |
| 3 | Circuit description + device/pin/net graph (paper §1.4) | **Done** (graph export only; nothing learns from it yet) |
| 4 | Floorplanner: DRR padding (Eq. 2) + simulated annealing over sequence pairs (Eq. 1 cost) | **Done.** Placed floorplans DRC clean on both PDKs |
| 5 | Router between blocks: two-layer grid, bidirectional A* with the paper's costs (Eq. 3–5), MST decomposition, rip-up and reroute | **Done.** Routed OTA: klayout + magic DRC clean and **end-to-end LVS match** on gf180 and sky130 |
| 5b | Router feedback into the floorplanner (the paper's named future work) | **Done.** Router check inside the annealer, plus a closed loop that grows padding only where routing fails ([§6](#6-phase-5-inter-block-router-and-router-feedback)) |
| 6 | R-GCN + PPO | Not started. The graph export and the SA floorplanner (as a data generator) are the inputs it needs |

Every significant call prints a **process table** in the terminal (see [§4](#4-process-tables)).

---

## 1. Files

### New

| File | What it does |
|---|---|
| [util/process_table.py](gLayout/src/glayout/util/process_table.py) | `ProcessTable` (timed stages + results, printed on exit, also on error) and `print_table` for data tables. `rich` rendering with ASCII fallback |
| [placement/finger_sequence/model.py](gLayout/src/glayout/placement/finger_sequence/model.py) | Geometry-free row model: `DeviceSpec`, `Finger`, `FingerSequence` (contacts, segments, breaks, centroids, 2nd moments, drain balance), `DiffusionGraph` (Euler lower bound on breaks) |
| [placement/finger_sequence/search.py](gLayout/src/glayout/placement/finger_sequence/search.py) | `search_sequences`: enumerate orders (exhaustive / palindromes / seeded sample), orientation DP, weighted score, ranked candidates |
| [placement/finger_sequence/layout.py](gLayout/src/glayout/placement/finger_sequence/layout.py) | `finger_sequence_row`: draws a sequence for a PDK. `finger_sequence_netlist`: LVS reference |
| [cells/elementary/finger_sequence/](gLayout/src/glayout/cells/elementary/finger_sequence/finger_sequence_cells.py) | `finger_sequence_cell` (generic), `cc_current_mirror`, `cc_diff_pair`: row + tie ring + well + gf180 labels + netlist |
| [floorplan/block.py](gLayout/src/glayout/floorplan/block.py) | `Block`, `Variant`, `Pin`, `Padding`; `build_block` builds variants and extracts pins |
| [floorplan/drr.py](gLayout/src/glayout/floorplan/drr.py) | `apply_drr` (paper Eq. 2), `block_keepout`, `routing_track` |
| [floorplan/circuit.py](gLayout/src/glayout/floorplan/circuit.py) | `Circuit` (instances, nets, symmetry), `graph()` → typed device/pin/net graph with feature vectors |
| [floorplan/sequence_pair.py](gLayout/src/glayout/floorplan/sequence_pair.py) | Sequence-pair packing (O(n²) longest path) |
| [floorplan/anneal.py](gLayout/src/glayout/floorplan/anneal.py) | `anneal_floorplan`: SA with Eq. 1 cost, variant moves, symmetry legalisation |
| [floorplan/realize.py](gLayout/src/glayout/floorplan/realize.py) | `realize_floorplan`: places the cells, checks block gaps, flattens |
| [floorplan/examples.py](gLayout/src/glayout/floorplan/examples.py) | Two-stage OTA example (4 blocks, 11 variants); `bias_bank`, `cs_stage` cells; `two_stage_ota_routed` (floorplan + route, `mode="drr"` or `"closed_loop"`) |
| [floorplan/router.py](gLayout/src/glayout/floorplan/router.py) | `RouterTech` (pitch/pads from the PDK), `RoutingGrid`, pin-access planning, `bidirectional_astar`, `route` (MST + rip-up/reroute) |
| [floorplan/route_flow.py](gLayout/src/glayout/floorplan/route_flow.py) | `problem_from_placement`, `make_route_check` (router inside the annealer), `closed_loop_floorplan`, `route_floorplan` (draws wires, labels, composed LVS netlist) |
| [tests/test_finger_sequence.py](gLayout/tests/test_finger_sequence.py), [tests/test_floorplan.py](gLayout/tests/test_floorplan.py), [tests/test_router.py](gLayout/tests/test_router.py) | 21 PDK-free unit tests (pytest, or run the file directly: pytest isn't in the venv) |
| `tests/parameters/finger_sequence_*.csv`, `floorplan_*.csv`, `routed_*.csv` | DRC/LVS parameter sets for the new cells, floorplans and routed floorplans. Separate from the CI CSVs, so default CI is unchanged |
| [glayout-work/framework_benchmark.py](glayout-work/framework_benchmark.py) | Mirror comparison, DRR ablation, routing by flow; writes `glayout-work/results/framework_benchmark_<pdk>.json` |

### Modified (existing test infrastructure: real bugs found along the way)

| File | Change | Why |
|---|---|---|
| [tests/lvs/klayout_gf180.py:217](gLayout/tests/lvs/klayout_gf180.py:217) | Copy the reference spice next to the staged netlist and `.include` that copy | klayout's SPICE reader ends an `.include` path at `-`, so in a checkout called `glayout-martin/` **every gf180 LVS failed** with `Read error on file: /foss/designs/glayout`. Baseline `current_mirror_nfet` failed before and passes after |
| [tests/drc/run_cell_drc.py](gLayout/tests/drc/run_cell_drc.py) `_run_magic_drc` | Error if the GDS top cell isn't named as the design | magic prints `Cell X couldn't be read`, writes an empty report, and the runner counted that as a **clean pass**. Hit by gdsfactory's `name$1` renaming |
| [tests/drc/run_cell_drc.py](gLayout/tests/drc/run_cell_drc.py) `_CELL_BUILDERS` | 14 new entries | Register the new cells, floorplans and routed floorplans |

No existing generator was changed: `current_mirror`, `diff_pair`, the interdigitized macros and the fet primitive produce the same geometry as before.

---

## 2. Phase 1: finger-sequence generator

### Why
The notes' open question (§2.9) has a definite answer: gLayout shared diffusion **only between fingers of the
same transistor**. `macro_two_transistor_interdigitized` draws every A/B column as its own multiplier with
`active_diff` spacing between them, so ABAB… has a diffusion break at every boundary, and each finger has its own
drain region. Its ABAB order is not common-centroid either: the A and B centroids sit one column apart.

### What
A row is a sequence of unit fingers, e.g. `A+ A- B+ B- B+ B- A+ A-` (`+` = source on the left).

```
search_sequences(devices)         finger_sequence_row(pdk, seq)            finger_sequence_cell
 1 diffusion graph → bound         1 one diffusion strip per segment        1 search or given sequence
 2 orders: all / palindromes       2 one met2 rail per S/D net (above)      2 row
 3 orientation DP (breaks, drains) 3 one rail per gate net (below)          3 tie ring, dummies → ring
 4 score + rank                    4 dummies, merged implant                4 well, gf180 labels, netlist
                                   5 C route where a net is both gate       5 flatten
                                     and S/D (diode connection)
```

Design points:
- **Rails by net, not by device.** That generalises the `shared_gate` change. A current mirror gets three S/D
  rails (VSS, VREF, VOUT) and one gate rail, with no source short and no gate short needed.
- **Geometry reuses proven code.** Fingers come from `fet.__gen_fingers_macro`. Rail heights, gate-bar levels and
  dummy construction copy `multiplier` / the interdigitized macro (rail k at `sep + h/2 + k·(h + sep)`, gate level
  pitch `bar + 2·max_metal_sep`). The dogbone handling for narrow fingers comes along for free.
- **Score** (weights in `SequenceWeights`): centroid error ×1000, breaks ×100, drain imbalance ×50, second-moment
  mismatch ×1, drain contacts ×0.5. With these, the 4+4 mirror picks the notes' `AABBBBAA` (balanced drains) over
  `ABBAABBA` (0.25 imbalance). For 8+8 it finds `AABBBBAABBAAAABB`, which also has zero second-moment mismatch, so
  quadratic gradients cancel too.
- **Centroids are measured on the drawn layout** (gate x positions) and reported in the row's table and `info`.
- **The cell is flattened.** magic types devices per GDS cell: a pfet row in a subcell, with the nwell in the
  parent, reads as p+ substrate taps (`P-Ohmic`) and gives ~475 errors. The existing `current_mirror` is only
  immune because its gf180 labelling step happens to flatten.
- **Naming:** the final name goes on the flattened cell, and internal names differ from runner names
  (`cc_cmirror_nfet`, …). gdsfactory appends `$1` to any name assigned twice in a process.
- **Netlist:** one line per device with `m` = finger count, plus dummies on the bulk. No parameters on the
  top `.subckt` line: with them, klayout fails with "Can't find a schematic counterpart for the top cell".

### Checks

All klayout DRC, magic DRC (the cells are actually read: 0 "couldn't be read") and LVS:

| Cell | Sequence | gf180 | sky130 |
|---|---|---|---|
| `cc_current_mirror` nfet, 4+4 | AABBBBAA | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `cc_current_mirror` pfet, 4+4 | AABBBBAA | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `cc_current_mirror` 1:2 (2+4) | BBAABB | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `cc_diff_pair` nfet, 4+4 | AABBBBAA, 2 gate rails | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `cc_diff_pair` pfet, 4+4 | AABBBBAA | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `cc_diff_pair` 2+2, W=6 µm | ABBA (single-finger gate groups) | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `cc_diff_pair` 8+8, W=1.5 µm | 16 fingers | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `bias_bank` ×1 (R:T:K = 2:4:4, 3 devices) | 10 fingers | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `bias_bank` ×2 (4:8:8), W=1.5 µm | 20 fingers, palindrome search | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `cs_stage` 8 fingers (1 device) | | ✅ ✅ ✅ | ✅ ✅ ✅ |

Columns per PDK: klayout DRC, magic DRC, LVS (gf180: klayout deck; sky130: magic + netgen). 10 cells × 2 PDKs,
all clean. The baseline `current_mirror_nfet` passes too after the LVS include fix.

---

## 3. Phases 2–4: blocks, DRR, annealer

### Blocks and variants
`build_block(pdk, name, kind, builder, variants)` builds each variant and extracts one `Pin` per net from
`component.info["pins"]`: the pin sits at the mean of the given ports, with sides taken from their orientations.
For finger-sequence cells, a rail's two ends are the pin (sides `EW`); the bulk is the tie ring (`NESW`).
Variants keep the circuit fixed and change the shape: the same total W as 2×6 µm, 4×3 µm or 8×1.5 µm fingers.
For the DP that gives aspect ratios 1.0, 1.75 and 3.13.

### DRR padding (paper Eq. 2)
`λ_[h,v] = ζ + |p_[h,v]| · track`, where one track is the inter-block router's pitch on its layers (met3/met4
by default: via pad + spacing = 0.8 µm in gf180, 1.9 µm in sky130; see §6). Before the router existed this was
min width + min spacing on met2/met3 (0.59 µm), and the floorplan numbers in §5 were updated when it changed.

**Deviation:** the paper's ζ is the placement grid step. Here ζ = ½ × the largest inter-block spacing rule (wells,
taps, metals: 0.7 µm in gf180, from nwell spacing 1.4 µm). Any two padded blocks that touch are then DRC-legal with
each other, even with `scale=0`. `scale` multiplies the track term (1 = paper, 0 = Table 5 "without DRR").

### Annealer (paper Eq. 1 as a cost)
`α·F_area/ΣA + β·HPWL/HPWL_ref + γ·(Ar*−Ar)² + δ·asym`, with α=10, β=100, γ=5 (the paper's) and δ=50.
- HPWL uses real pin positions of the chosen variant. HPWL_ref is the best of 200 random states; the paper uses
  the best metaheuristic result.
- Moves: swap in Γ+, in Γ-, in both; change a block's variant (its symmetric partner follows).
- **Symmetry** (not in the paper, which only rejects violations with −1000): after packing, self-symmetric
  blocks and symmetric pairs are slid onto the floorplan's vertical centre line where that is free. The residual
  distance is the `asym` term, so the annealer learns to leave the axis free.
- **SA instead of RL:** it needs no training, it gives the HPWL_min reference the paper needs anyway, and it can
  generate training data for Phase 6.

### Checks
- Realised two-stage OTA floorplans, with and without DRR: klayout and magic DRC clean on gf180 and sky130.
- Unit tests: packing never overlaps (200 random cases), the annealer is deterministic per seed and legal, the
  graph has the expected nodes and edge types.

---

## 4. Process tables

Each of these prints a table of its stages (status, time, details) plus a one-line result summary:

| Call | Stages |
|---|---|
| `search_sequences` | eligibility, diffusion graph + Euler bound, enumeration mode, orient + score, rank; then a top-5 ranking table and the row diagram |
| `finger_sequence_row` | W/L, diffusion segments, S/D rails, gate bars + rails, dummies, ties, measured centroids |
| `finger_sequence_cell` | sequence, row, tie ring, well, labels, netlist, flatten |
| `build_block` | one stage per variant (size, pins) |
| `apply_drr` | per block: pin counts, λ_h/λ_v, area growth |
| `Circuit.graph` | node and edge counts |
| `anneal_floorplan` | HPWL reference, initial state, T0, anneal, best cost terms; then a trace table and a placement table |
| `realize_floorplan` | per instance + minimum block gap |
| `route` | grid, pin access (sides used, unreachable pins), route + rip-up/reroute, result; then a rip-up table when it took more than one iteration |
| `closed_loop_floorplan` | one stage per round (dead space, routed or failed, which blocks grew); then a rounds table |
| `route_floorplan` | realise, placement-vs-router consistency check, route, draw, labels, netlist, flatten |
| `framework_benchmark.py` | mirror comparison, DRR ablation, routing by flow |

Controls: `GLAYOUT_TABLES=0` silences everything. `GLAYOUT_TABLES_DEPTH=1` keeps only top-level calls; a
floorplan run nests block → cell → row → search, and prints ~650 lines at full depth.

---

## 5. Results

### Current mirror: existing `current_mirror` (ABAB) vs `cc_current_mirror`

Same devices (W=3 µm fingers, L=min), both with dummies and tie ring. The ABAB centroid error is one column
pitch of the interdigitized macro, which holds for any number of columns.

| PDK | Fingers | Cell | Sequence | Size µm | Area µm² | Δ area | Breaks | Centroid error | Drain regions / finger |
|---|---|---|---|---|---|---|---|---|---|
| gf180 | 2+2 | current_mirror | ABAB | 17.47×9.18 | 160.4 | | 3 | 2.53 µm | A 1.0, B 1.0 |
| gf180 | 2+2 | cc_current_mirror | ABBA | 13.06×8.94 | 116.8 | **−27.2%** | 0 | 0 | A 1.0, B 0.5 |
| gf180 | 4+4 | current_mirror | ABABABAB | 27.60×9.18 | 253.4 | | 7 | 2.53 µm | A 1.0, B 1.0 |
| gf180 | 4+4 | cc_current_mirror | AABBBBAA | 17.62×8.94 | 157.5 | **−37.8%** | 0 | 0 | A 0.5, B 0.5 |
| sky130 | 2+2 | current_mirror | ABAB | 12.62×8.29 | 104.6 | | 3 | 1.64 µm | A 1.0, B 1.0 |
| sky130 | 2+2 | cc_current_mirror | ABBA | 9.30×7.94 | 73.8 | **−29.4%** | 0 | 0 | A 1.0, B 0.5 |
| sky130 | 4+4 | current_mirror | ABABABAB | 19.18×8.29 | 159.0 | | 7 | 1.64 µm | A 1.0, B 1.0 |
| sky130 | 4+4 | cc_current_mirror | AABBBBAA | 11.90×7.94 | 94.5 | **−40.6%** | 0 | 0 | A 0.5, B 0.5 |

`current_mirror` here is the net-aware version (§7: one source rail, no shorts), which is itself 1.34 µm (gf180) /
0.98 µm (sky130) shorter than the shared-gate version. Against that older mirror the savings were −36.5% / −45.8%
(gf180) and −36.9% / −46.9% (sky130).

"Drain regions / finger" is a proxy for drain junction capacitance: 0.5 means every drain diffusion serves two
fingers. At 2+2 the A/B drain imbalance cannot be avoided (the notes' plain-ABBA case). Use ≥4 fingers per device
where drain balance matters.

### Two-stage OTA floorplan: DRR ablation (paper Table 5 analogue)

| PDK | Variant | Dead space | HPWL µm | Area µm² | Symmetry residual |
|---|---|---|---|---|---|
| gf180 | with DRR | 53.5% | 108.7 | 1388 | 0 |
| gf180 | without DRR | 27.2% | 93.4 | 885 | 0 |
| sky130 | with DRR | 77.7% | 121.6 | 1815 | 0 |
| sky130 | without DRR | 29.4% | 83.1 | 567 | 0 |

(Track = the router's pitch: 0.8 µm gf180, 1.9 µm sky130. With the earlier min-width + min-spacing track of 0.59 /
0.42 µm the "with DRR" rows were 48.1% / 104.7 µm and 51.1% / 93.0 µm.)

Same direction as the paper (57.4% / 797 µm with DRR, 37.3% / 673 µm without; different circuits and process).
All seeds reach the same floorplan: with four blocks the search space is small. Routability: §6.

---

## 6. Phase 5: inter-block router and router feedback

### Router ([floorplan/router.py](gLayout/src/glayout/floorplan/router.py))

Follows the paper's §1.10, step by step:

| Paper | Here |
|---|---|
| 3-D grid, step = min valid spacing, one H and one V layer, vias between | met3 horizontal, met4 vertical. Pitch = largest *via pad + spacing* of the two layers (0.8 µm gf180, 1.9 µm sky130), so a via or wire end on any node is legal beside any neighbouring track. Cells are obstacles: nodes and edges whose shapes would come within spacing of a cell bbox are removed |
| Pins projected to the block side that minimises the net's HPWL, all side combinations tried | Same, exhaustively up to 4096 combinations per net. Rail pins offer W/E, the tie ring N/E/S/W. Each pin gets a stub on its own layer (met1/met2) to a landing point outside its cell, plus a via stack up to the router layer |
| Multi-pin nets → two-pin connections by MST | Prim's MST order; each new pin is routed to the net's tree so far |
| Net order: past failures, then HPWL, then pins | Same |
| Bidirectional A*, D = Manhattan + c_via·Δz, g adds c_DRC·[violation] + H(n), h·(1+q), dynamic weighting κ=3 (Eq. 3–5) | Same, with c_via = 2 pitch, c_DRC = 20 pitch, q = 1e-4. "Violation" = entering a node another net uses (overlap). Search stops at the first meeting of the two frontiers |
| Rip-up and reroute, raise H on the nodes a violating net used, 35 iterations | Same; H += 2 pitch per rip-up |
| Low-bending rule | The layers are directional, so every bend is a via and the via cost is the bending cost |
| Minimum-width wires | **Deviation:** wires are drawn at via-pad width, so a via never needs extra enclosure |

**Pin access** was where the DRC/LVS checks found real problems. Fixed in this order:
1. Landing pads are off-grid (rails sit wherever the cell put them). Every grid node or edge whose wire would come within
   spacing of a landing pad is *reserved for that landing*: usable only as the pin's direct neighbour, so its wire
   touches the pad. A same-net wire or via passing *near* the pad is still a spacing (or via-cut) violation, so the
   pin's own net is kept out too.
2. A new landing must leave every pin already landed (and itself) an escape to an unreserved node; otherwise it
   moves one track further out. Without this a VDD pin landed boxed in by its neighbours' pads and the net failed.
3. Stubs that cross in-cell metal: in sky130 the mirror's diode-tie C route has a met2 pad wider than the rails,
   reaching into the neighbouring rail's corridor, and a VDD stub along that corridor shorted VREF to VDD. LVS
   caught it; DRC can't (it is a legal short). `extract_pins` now records, per access port, the cell's other shapes
   along the corridor, each with the spacing to keep. That is the layer rule, or the spacing the cell already has to
   the port's own metal: a stub that continues a rail keeps the rail's spacing. glayout's gf180 met2 rule is 0.3 µm,
   while the deck's M2.2a is 0.28 µm and the rails sit 0.29 µm apart.
4. A bug: pin nodes reported their landing index as their layer, so every pin connection drew a via instead of a
   wire. That caused DRC errors and the open that left the substrate (`SUB`) off VSS in the first gf180 LVS.

### Changes to the earlier framework files

| File | Change |
|---|---|
| [floorplan/block.py](gLayout/src/glayout/floorplan/block.py) | `Access` per port (side, position, layer, width, foreign shapes along its corridor); `Pin.access` |
| [floorplan/realize.py](gLayout/src/glayout/floorplan/realize.py) | `cell_origin`: cells land exactly on the 2x-grid origin the router assumes (the move is no longer snapped); `flatten=False` option |
| [floorplan/drr.py](gLayout/src/glayout/floorplan/drr.py) | Track = router pitch; per-block `scales` for the closed loop |
| [floorplan/anneal.py](gLayout/src/glayout/floorplan/anneal.py) | `route_check` / `route_weight`; router-call count in the table |
| [floorplan/circuit.py](gLayout/src/glayout/floorplan/circuit.py) | `Circuit.ports` (top-level pins for labels and the LVS netlist) |

### Router feedback

- **In the annealer** (`anneal_floorplan(route_check=...)`): every candidate that would become the new best is routed
  first (cached per state), and each failed net or unreachable pin adds 200 to its cost.
- **Closed loop** (`closed_loop_floorplan`): start with no DRR padding, anneal, route, and grow the DRR scale by
  0.25 on the blocks nearest to where routing failed (conflict nodes after rip-up and reroute, pins with no landing);
  repeat until it routes.
- **Finding:** the in-annealer check alone is the weaker form. With little padding most compact floorplans fail,
  the penalty pushes the walk to sparse ones, and the result was 63% dead space vs 42% for the closed loop (gf180,
  seed 0) at ~1500 router calls. So the closed loop runs without it by default (`in_loop=False`).

### Checks

| Layout | gf180: klayout DRC / magic DRC / LVS | sky130 |
|---|---|---|
| Routed OTA, paper flow (`routed_two_stage_ota_drr`) | ✅ ✅ ✅ | ✅ ✅ ✅ |
| Routed OTA, closed loop (`routed_two_stage_ota_closed_loop`) | ✅ ✅ ✅ | ✅ ✅ ✅ |

LVS compares the whole routed OTA (4 cells, 25 devices with dummies) against the netlist composed from the cells'
netlists and the circuit's nets. Top-level labels go on met2 at a rail end of each external net; the cells are built
without their own labels. `two_stage_ota_routed(strict=True)`, the runner's builder, raises if routing fails, so an
unrouted layout can never pass DRC unnoticed.

Unit tests ([tests/test_router.py](gLayout/tests/test_router.py)): straight connection, detour round an obstacle,
unroutable detection, a one-track channel that fits one net but not two (fails after the iteration limit), a channel
two nets share after rip-up and reroute, staggered landings for close pins, Eq. 5.

### Results: routing by flow (paper Table 1 analogue)

Ten seeds per flow (three for the slow in-loop flow), two-stage OTA, every floorplan routed by the inter-block
router. Means are over routed runs. "Failure" = the router could not connect every net or land every pin.

| PDK | Flow | Runs | Failure rate | Dead space | Area µm² | HPWL µm | Routed WL µm | Vias | RRR it. | s / run |
|---|---|---|---|---|---|---|---|---|---|---|
| gf180 | no DRR | 10 | 100% | 26.6% | — | — | — | — | — | 0.3 |
| gf180 | DRR (paper, scale 1) | 10 | **20%** | 53.9% | 1383 | 108.3 | 265.5 | 55.0 | 2.0 | 0.3 |
| gf180 | closed loop | 10 | **0%** | **42.7%** | **1121** | 100.7 | 271.3 | 49.6 | 8.3 | 1.0 |
| gf180 | closed loop + router in annealer | 3 | 0% | 63.3% | 1924 | 190.5 | 273.8 | 57.7 | 2.0 | 151 |
| sky130 | no DRR | 10 | 100% | 28.2% | — | — | — | — | — | 0.3 |
| sky130 | DRR (paper, scale 1) | 10 | 0% | 77.9% | 1820 | 122.1 | 312.6 | 43.4 | 2.0 | 0.3 |
| sky130 | closed loop | 10 | 0% | **71.6%** | **1422** | 111.4 | 323.1 | 44.1 | 2.0 | 1.4 |
| sky130 | closed loop + router in annealer | 3 | 0% | 72.2% | 1509 | 169.3 | 341.1 | 49.7 | 4.3 | 461 |

Reading it:
- **Padding is needed:** with ζ alone (no track term) no floorplan routes on either PDK. Pins have nowhere to land,
  and the supply nets can't get past the stacked blocks.
- **The paper's fixed padding is not enough everywhere and too much elsewhere:** on gf180 it still fails 2 of 10
  seeds, while on sky130 (1.9 µm pitch) it routes but leaves 78% dead space.
- **The closed loop routes every seed on both PDKs with less area:** −19% area on gf180, −22% on sky130, and lower
  HPWL. On the gf180 seeds inspected (0–4) it settled at DRR scale 0.5 on every block, because every block is on a
  congested supply net; on wider floorplans the hotspot-targeted growth should leave quiet blocks unpadded (not
  yet shown).
- **The router inside the annealer is the weaker form of feedback:** 150–460 s per run, and it drives the search to
  sparse floorplans, as found above.
- **Comparison with the paper (Table 1):** routing-aware 9.6% failure vs 79–83% for the earlier RL. Different
  circuits, process and router, so only the direction carries over: padding sized by router feedback beats a fixed
  formula.

The DRR ablation in §5 was rerun with the router pitch as the track: gf180 53.5% / 108.7 µm with DRR vs 27.2% /
93.4 µm without; sky130 77.7% / 121.6 µm vs 29.4% / 83.1 µm. The large sky130 figure comes from its 1.9 µm pitch
(see §7).

---

## 7. Net-aware interdigitized rails: no shorts left

### Why
`shared_gate` fixed one case of a general problem in `macro_two_transistor_interdigitized`: rails were assigned per
*terminal*, and B's rails pushed past A's. So every caller whose terminals share a net drew extra rails and then
shorted them with C routes:

| Where | Before | Now |
|---|---|---|
| `current_mirror` | 2 source rails + E-side C route (source short) + W-side C route (diode) | 1 source rail; the macro draws the one diode tie |
| `opamp` output-stage bias mirror | 2 gate rails + C route + L route to the drain; 2 source rails + C route as a ground tap | 1 gate rail + 1 diode tie; 1 source rail + a rail tap |
| `diff_pair_cmirrorbias` tail mirror | the same two shorts | the same as `opamp` |
| `smart_route` on an interdigitized row | a C route or via-stack trick for `A_source↔B_source`, `A_gate↔B_gate` | nothing, when the row's nets say they are already one net |

The macro also wasted space where nets were distinct: B's first source/drain rail sat `max_metal_sep + h + rail
offset` above A's drain rail (0.55 µm more than one pitch in gf180), and B's gate bar two metal spacings below A's
(one is enough). Both are gone, so every row is shorter.

### What
| File | Change |
|---|---|
| [primitives/fet.py](gLayout/src/glayout/primitives/fet.py) `multiplier` | `source_route_extension` / `drain_route_extension` (default: `sd_route_extension`, so callers are unchanged) |
| [placement/two_transistor_interdigitized.py](gLayout/src/glayout/placement/two_transistor_interdigitized.py) | `nets` (terminal → net), `diode_tie_side`, `diode_tie_viaoffset`; one S/D rail per distinct net, stacked at one pitch (A_source, A_drain, then B's new nets); B's own gate rail one spacing below A's; aliased ports for shared rails; the C route for each gate net that is also an S/D net; `info["nets"]`; `interdigitized_nets()`; `rail_tap()`. `shared_gate` is now shorthand for `B_gate = A_gate` |
| same, `two_tran_interdigitized_netlist` | `nets`: terminals on one net share one pin (the first of VDD1 VDD2 VSS1 VSS2 VG1 VG2) |
| [cells/elementary/current_mirror/current_mirror.py](gLayout/src/glayout/cells/elementary/current_mirror/current_mirror.py) | `MIRROR_NETS`; no source short, no diode C route; the netlist uses the merged pins; the VSS label sits inside the source rail (it used to rely on the source-short stub to cover half of it: magic M2.1 sliver otherwise); `purposegndports*` ports removed (they were the source short's, and nothing used them) |
| [cells/composite/opamp/opamp.py](gLayout/src/glayout/cells/composite/opamp/opamp.py) | output-stage bias mirror built with `MIRROR_NETS`, tie on E; ground via `rail_tap` on the source rail's W end |
| [cells/composite/diffpair_cmirror_bias/diff_pair_cmirrorbias.py](gLayout/src/glayout/cells/composite/diffpair_cmirror_bias/diff_pair_cmirrorbias.py) | tail mirror the same way; `rail_tap` keeps the `purposegndportscon_S` port the VSS label and `diff_pair_stackedcmirror` use |
| [routing/smart_route.py](gLayout/src/glayout/routing/smart_route.py) | returns an empty route for two terminals the row already joins (shared rail or diode tie) |
| [tests/test_netaware_interdigitized.py](gLayout/tests/test_netaware_interdigitized.py) | 6 tests: rail count, aliases, uniform pitch, merged netlist pins, `smart_route` no-op, no shorts in `current_mirror` |

The diode tie keeps the same geometry `current_mirror` had (W side, 3·max-metal-spacing, `viaoffset=False`). On the
composites' met3 rails `viaoffset=False` leaves a ~30 nm gap between via and stub, the case their own comment
already describes; that showed up as sky130 m2.2 errors and an open, so they pass `diode_tie_viaoffset=None`.

### Size, before → after (fingerprints of the built cells)

| Cell | gf180 | sky130 |
|---|---|---|
| `current_mirror` (numcols 1–3, nfet/pfet) | 10.52 → **9.18 µm** tall (−12.7%) | 9.27 → **8.29 µm** (−10.6%) |
| `two_nfet_interdigitized`, distinct nets (numcols 1–3) | 17.38 → 16.54 µm | 11.81 → 10.85 µm |
| `two_nfet_interdigitized`, `shared_gate` | 16.28 → 15.74 µm | 10.68 → 10.13 µm |
| `generic_4T_interdigitzed` | 24.70 → 23.02 µm | 22.37 → 20.45 µm |
| `diff_pair_ibias` (CI parameters) | 43.08 → 40.36 µm | 34.70 → 32.20 µm |
| `opamp` (CI parameters) | outline unchanged (set by other blocks), 48 fewer polygons | 106.22 → 103.49 µm |
| `differential_to_single_ended_converter`, `low_voltage_cmirror` | **byte-identical** (don't use the macro) | **byte-identical** |

Widths do not change: both old C routes sat over the dummies' footprint.

### Checks

Every cell that uses the macro, on both PDKs: klayout DRC / magic DRC / LVS, compared with the same checks on the
committed code (`HEAD` = the shared-gate commit, extracted with `git archive` and run with the fixed test runner).

| Cell | gf180 now | gf180 at HEAD | sky130 now | sky130 at HEAD |
|---|---|---|---|---|
| `current_mirror` nfet/pfet × numcols 1, 2, 3 (6 cells) | ✅ ✅ ✅ | ✅ ✅ ✅ | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `diff_pair_ibias` | ✅ ✅ ✅ | ✅ ✅ ✅ | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `generic_4T_interdigitzed` | PP.2 ×3, LVS `SUB` pin | same | ✅ ✅ ✅ | ✅ ✅ ✅ |
| `opamp` (CI parameters, no output stage) | ✅ ✅, LVS: MIM cap missing | same | ✅, magic 138 (diff/tap.3), LVS 1 mismatch | same |
| `opamp` with output stage (changed bias mirror) | M4.2a ×5 + LPW.2b, magic 2, LVS 8 | same | ✅, magic 138, LVS fail (0 mismatches) | same |

So every failure in the table already exists at `HEAD`. None of them is in a mirror this change touched: the gf180
M4.2a errors are at y ≈ 88 µm in the opamp body, far from the output stage. The checks found and fixed three
regressions along the way:
1. The current mirror's VSS label hung half off the rail end once the source-short stub was gone (magic M2.1).
2. Met3 rails with the tie's `viaoffset=False`: a 30 nm via gap (sky130 m2.2, and an open: LVS).
3. In the opamp output stage on sky130 the VREF and VOUT rails became neighbours, and the diode tie's and the
   B-drain route's 1.5 µm met4 via pads overlapped (a VREF–VOUT short). Fixed with `rail_order=["VREF","VSS","VOUT"]`.

Byte-identical to `HEAD` (geometry hash): `diff_pair`, `flipped_voltage_follower`, `transmission_gate`,
`nmos/pmos_narrow`, default `nmos`, `pmos(fingers=4, multipliers=3)`, `multiplier(sd_route_extension=0.7)`,
`differential_to_single_ended_converter`, `low_voltage_cmirror`, on both PDKs.

Unit tests: 7 in `test_netaware_interdigitized.py`; all 28 framework tests pass.

---

## 8. Known limitations and next steps

| Item | Notes |
|---|---|
| Larger benchmarks | Four blocks are a small search space: every seed reaches the same floorplan. The router and closed loop need bigger circuits (delay line, multi-stage amplifiers) to show failure *rates* rather than a single outcome |
| sky130 pitch 1.9 µm | glayout's sky130 rules give via3 a 0.65 µm met4 enclosure (the PDK's is 0.065 µm), so `via_stack(met3, met4)` has a 1.5 µm met4 pad. Left alone because changing it moves other cells; fixing it would cut the sky130 router pitch to about 0.9 µm |
| Router search | Bidirectional A* stops at the first meeting, so paths are not always shortest. The rip-up loop does not report per-connection failures, only per net |
| Over-the-cell routing | Cells are full obstacles on met3/met4, as in the paper, although the cells use no met4. Allowing met4 over cells would free a lot of room |
| No symmetric or matched routing | As in the paper: DP/LOAD nets are not routed symmetrically |
| 2-D common centroid | Only single rows. Two-row cross-coupled patterns (notes §2.9) need inter-row rail straps |
| Cross-block merge (notes §2.5, option 2) | Not done: e.g. cascode + mirror as one stacked cell |
| Symmetry is soft | Legalisation + penalty. Results so far have 0 residual, but a symmetric-feasible sequence pair would make it a hard constraint |
| HPWL uses rail centres | The annealer's HPWL takes a pin at its rail's centre; the router then picks the side. Using the projected side in the cost would make HPWL track the routed wirelength better |
| DRR counts the bulk ring as h and v | Slight over-padding; the bulk is usually connected by abutting rings or straps |
| Existing `diff_pair` (gf180): 1 magic violation | `Metal2 spacing < 0.28um (M2.2a)`; klayout DRC and LVS pass. Pre-existing: no geometry code was changed. Found in the regression run (`current_mirror_nfet/pfet` clean) |
| Existing composites still hand-placed | `opamp`, `diff_pair_ibias` etc. no longer short anything internally (§7), but their blocks are still placed by hand. They can move to the floorplanner once blocks publish `info["pins"]` |
| Pre-existing failures the new checks found | At `HEAD` and now: gf180 `generic_4T_interdigitzed` PP.2 ×3 + LVS `SUB` pin; gf180 `opamp` LVS (MIM cap not extracted); gf180 output-stage `opamp` M4.2a ×5 (y ≈ 88 µm) + LPW.2b + LVS; sky130 `opamp` 138 magic diff/tap.3 + LVS. None of these is in this work's code; worth separate fixes |

## 9. Reproducing

Inside the iic-osic-tools container:

```bash
export PATH=/foss/designs/glayout-martin/.venv/bin:/foss/tools/klayout:/foss/tools/bin:$PATH
cd /foss/designs/glayout-martin/gLayout
python tests/test_finger_sequence.py && python tests/test_floorplan.py && python tests/test_router.py && python tests/test_netaware_interdigitized.py
python tests/drc/run_cell_drc.py --pdk gf180 --params tests/parameters/netaware_gf180.csv --engine both --out-dir /tmp/na_drc   # mirrors, 4T, diff_pair_ibias, opamp (± output stage)
python tests/lvs/run_cell_lvs.py --pdk gf180 --inputs-dir /tmp/na_drc --out-dir /tmp/na_lvs
python tests/drc/run_cell_drc.py --pdk gf180 --params tests/parameters/finger_sequence_gf180.csv --engine both --out-dir /tmp/fs_drc
python tests/lvs/run_cell_lvs.py --pdk gf180 --inputs-dir /tmp/fs_drc --out-dir /tmp/fs_lvs
python tests/drc/run_cell_drc.py --pdk gf180 --params tests/parameters/floorplan_gf180.csv --engine both --out-dir /tmp/fp_drc
python tests/drc/run_cell_drc.py --pdk gf180 --params tests/parameters/routed_gf180.csv --engine both --out-dir /tmp/rt_drc
python tests/lvs/run_cell_lvs.py --pdk gf180 --inputs-dir /tmp/rt_drc --out-dir /tmp/rt_lvs
cd .. && python glayout-work/framework_benchmark.py --pdk gf180          # --skip-in-loop to drop the slow flow
```

Minimal use:

```python
from glayout import gf180 as pdk
from glayout.cells.elementary.finger_sequence import cc_current_mirror, finger_sequence_cell
cm = cc_current_mirror(pdk, fingers=4)                       # searches, draws, prints tables
bank = finger_sequence_cell(pdk, [dict(name="R", source="VSS", drain="IB", gate="IB", fingers=2),
                                  dict(name="T", source="VSS", drain="VT", gate="IB", fingers=4)])
from glayout.floorplan.examples import two_stage_ota_floorplan, two_stage_ota_routed
fp = two_stage_ota_floorplan(pdk, seed=0)                    # blocks → DRR → anneal → placed GDS
ota = two_stage_ota_routed(pdk, mode="closed_loop")          # ... → route → wires, labels, LVS netlist
ota.write_gds("two_stage_ota_routed.gds")
```
