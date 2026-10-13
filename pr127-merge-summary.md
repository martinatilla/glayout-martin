# Combining PR #127 with the floorplanning work: netlist → layout → learning

Status as of 2026-10-13. Phases 0–6 are committed (gLayout and the outer repo, both on branch
`learn-dataset`); the full label run and Phase 7 (training on external GPUs) have not started.

---

## 1. Why this was done

The review of gLayout PR #127 (Minxing's sharing + textbook benchmark) raised three problems:

1. **The baseline was not gLayout.** PR #127 drew every layout with its own rectangle generator
   (`build_mos_group`) and its own channel router, so its gains were measured against itself.
2. **Routing, not sharing, set the area.** Routing channels were 63 % of the layout height.
3. **Matching was ignored.** No declared matched pair ended up common-centroid.

Meanwhile the unpushed work on `my-new-feature` already had the pieces PR #127 lacked: common-centroid,
diffusion-shared finger rows built from gLayout's own primitives, a floorplanner (DRR padding + simulated
annealing), an A* router with router feedback, net-aware rails and a PEX/ngspice evaluation harness. What it
lacked was a way to get *many* circuits in: every floorplanned circuit had to be written by hand
(`floorplan/examples.py`).

The combination: take PR #127's best ideas (the AnalogGenie dataset, its 18 curated textbook circuits and their
declared matched pairs) and run them through **your** flow, so every layout is real gLayout geometry, and turn the
flow's results into training data for a model.

## 2. What came from where

| Source | What was used | What was *not* used |
|---|---|---|
| **PR #127** (`pr-127`) | The AnalogGenie dataset at the commit it cites (`efc2535`); its 18 curated topologies with book/page provenance; its 30 declared matched pairs (as ground truth for the annotator); the shape of its netlist data model; its habits of frozen splits and recording the code version with every result; its gf180 DRC deck fix (now a commit on `pr-127-review`) | `build_mos_group` (rectangle generator), the row/channel assembler, the 256-combination plan enumeration, the hand-written cost rule, the LLM experiments |
| **Your work** (`my-new-feature`) | `finger_sequence_cell` and its search (draws every block); `Block`, `Variant`, `Circuit`, `graph()`; DRR padding, annealer, closed loop, A* router, `route_floorplan`; net-aware rails; process tables; the DRC/LVS runners and their fixes; `glayout.evaluation` | — |
| **New** | `glayout.schematic` (netlist reader, annotator, sizing, schematic → circuit, graph format); `learn/` (dataset build, label jobs, audit); `glayout-work/demo_phases.py`; four bug fixes in existing code (§4) | — |

Code layout:

| Where | What | Branch |
|---|---|---|
| `gLayout/src/glayout/schematic/` | netlist-in library code: no machine learning, mergeable | gLayout `learn-dataset` |
| `gLayout/src/glayout/floorplan/`, `placement/finger_sequence/` | your floorplanner, router, finger rows (two router fixes) | gLayout `learn-dataset` |
| `learn/` | dataset, splits, label jobs, audit; later training | outer repo `learn-dataset` |
| `~/eda/designs/gLayout-pr127` | PR #127 checked out separately, with its unpacked data | gLayout `pr-127-review` |

## 3. The flow, end to end

```
AnalogGenie / curated netlist
   │  read            glayout.schematic.readers      Phase 1
   ▼
Schematic (devices, pins, nets, ports)
   │  annotate        glayout.schematic.annotate     Phase 2
   ▼
blocks + matched / symmetric devices
   │  size, build     glayout.schematic.sizing, to_circuit → finger_sequence_cell     Phase 3
   ▼
floorplan Circuit (blocks with 3 shapes each)  ──► graph (model input)          Phase 4
   │  closed-loop floorplan + A* route   (your floorplan/ code)
   ▼
routed layout (GDS + LVS netlist)  ──► labels (model targets)                   Phase 6
   │  KLayout DRC, magic DRC, LVS   (your test runners)
   ▼
verified layout
```

Phase 5 decides *which* circuits go through this flow and how they are split for training; Phase 7 will train a
model that predicts the flow's outcome from the graph.

## 4. Phase by phase

### Phase 0: branches

- PR #127's uncommitted gf180 DRC fix (`verify/drc.py`: use the `gf180mcu.drc` runset on newer open_pdks) became
  commit `c76c5e3` on `pr-127-review`, checked out in its own folder `~/eda/designs/gLayout-pr127` together with
  PR #127's unpacked case data and run records.
- The gLayout submodule works on `learn-dataset`, created from `my-new-feature` (`97f650d`).

### Phase 1: read netlists (`99c856b`)

**What it does:** turns any netlist into one common format, a `Schematic`: devices with named pins, the nets they
connect to, the ports, and where the circuit came from.

- `schematic/model.py`: `Device`, `Schematic`, pin names per device kind, net classes (power, ground, bias,
  clock, signal), structural checks, JSON save/load.
- `schematic/readers.py`: AnalogGenie entries and PR #127's curated circuits.
- Handles AnalogGenie's quirks: BJT lines with a fourth (substrate) net, subcircuits flattened into one file that
  repeat instance names, bodies on signal nets.
- Checked: all 18 curated circuits convert; curated C08 matches AnalogGenie entry 157 device for device.

### Phase 2: find the structure (`f82cac6`)

**What it does:** the step a designer used to do by hand when writing a `Circuit`: find the differential pairs,
mirrors, cascodes and bias banks, decide which devices must match, and group devices into blocks that one finger
row can draw.

- `schematic/annotate.py`: seeds (differential pairs, including degenerated ones; cross-coupled pairs; mirrors
  with evidence; diode/gate pairs), propagation (cascodes, loads, passives), blocks with one device type and one
  body each, labelled with your floorplanner's `KINDS`, and floorplan symmetry.
- Recovers **all 30** of PR #127's declared matched pairs (plus 4 extras, checked by hand); your two-stage OTA comes
  out as `DP`, `CM`, `BIAS`, `CS` with DP and the load self-symmetric.
- Three rules were corrected on real AnalogGenie circuits (a false mirror in a VCO, a cascode mirror in an LDO, a
  "cascode" merged through a port).

### Phase 3: from netlist to routed layout (`4acd5be`)

**What it does:** gives each block a size, draws it, and runs your floorplanner and router to a finished layout.

- `schematic/sizing.py`: synthetic sizes (length = 1, 2 or 4 × minimum; a unit width; base finger counts; three
  shapes per block with the same total width). Matched halves are sized alike. **Layout only: these sizes have no
  electrical meaning.**
- `schematic/to_circuit.py`: `schematic_to_circuit` builds every block with `finger_sequence_cell` (with a cache
  and canonical names) and returns your `Circuit`; `schematic_routed` runs the whole flow.
- `schematic/textbook.py`: the 18 curated circuits and the two-stage OTA, in the library.
- 15 entries `sch_*_routed` in your DRC runner (`tests/parameters/schematic_<pdk>.csv`).
- Result: the 15 MOS-only curated circuits are **15/15 clean on gf180** and 14/15 on sky130 (KLayout DRC, magic
  DRC, LVS). C18 on sky130 routes for one sizing in three.
- Router fix: two landings of the same net could overlap off-centre, putting their via cuts too close (gf180
  V2.2a/V3.2a).

### Phase 4: the graph the model reads (`ba5e0f1`)

**What it does:** describes each circuit as a graph a neural network can read.

- `schematic/graph.py`, `schematic/vocab.py`, `Circuit.hetero_graph()` (`Circuit.graph()` is unchanged).
- Two levels sharing their net nodes: devices, pins and nets; blocks and block pins; linked by device-in-block
  edges. Features: device 37, pin 16, net 11, block 22, block pin 16.
- Every file stores its schema version and feature names, so the GPU machine needs no gLayout.
- **No floorplan or routing result is ever a feature** (tested), so the model cannot cheat.

### Phase 5: the dataset (gLayout `60baa28`, outer repo `f98e495`)

**What it does:** collects the circuits, cleans them, removes duplicates, and freezes the train / validation /
test split so the model is graded honestly.

- `learn/data/fetch_analoggenie.sh`: AnalogGenie at `efc2535`, netlists only (no textbook scans).
- The reader also flattens the 32 `<id>_full.cir` netlists (inverters, transmission gates … into transistors)
  and reads the 770 `Opamp<id>.cir` error-amplifier extracts of the bandgap and LDO entries.
- `learn/data/ingest.py`: **4,120 items, 0 errors, 10 s**. **519 are drawable by the current flow** (MOS only,
  nfet bodies on ground, no MOS varactors, at most 12 blocks). Adding resistor/capacitor support would add ~1,400.
- `learn/data/wl.py`, `dedupe_split.py`: a topology hash groups duplicates; the curated circuits and their copies
  are the test set; the rest is 90/10 train/validation per category.
  **Train 3,689 / validation 413 / test 37** items (drawable: 458 / 50 / 26). Frozen in `learn/data/splits.json`.

### Phase 6: labels (gLayout `ea888c2`, outer repo: the commit adding `learn/labels/`)

**What it does:** runs your flow on every drawable circuit and records what happened. These are the answers the
model learns to predict.

- `learn/labels/run_flow.py`: per circuit, PDK, sizing and seed: the graph (saved before floorplanning) and the
  outcome: area, dead space, HPWL, wirelength, routed or not, rounds; padding and chosen shape per block;
  first-round failure per net. Resumable; failures are recorded, never dropped.
- `learn/labels/audit.py`: rebuilds a sample of layouts, runs DRC and LVS, and checks the rebuild reproduces the
  record exactly. `learn/labels/summarize.py` reports a run.
- **Pilot** (354 records, 103 min, 7 workers): gf180 **96 %** routed, sky130 **46 %**.
- Bugs found and fixed in existing code:
  - A* broke ties in the iteration order of a set whose order follows Python's string hashing, so the same circuit
    could route differently in two processes. Fixed; 16 circuit/PDK pairs × 3 hash seeds now give identical results.
  - `MappedPDK.lvs_netgen` overwrote the stored PDK path with `None`, so the next magic DRC in the same process
    failed. Fixed (a candidate for a small upstream PR).
  - Circuits with a MOS varactor (source = drain) are now reported as `mos_cap` instead of failing to build.
- After the fixes: 52 test-set records, **audit 20/20 clean (KLayout, magic, LVS) and 20/20 reproduced exactly**.
- Found: gLayout's sky130 table has via3/metal-4 rules up to 10× looser than the official deck (metal-4 enclosure
  of via3 0.65 vs 0.065 µm; metal-3 enclosure 0.19 vs 0.06 µm; metal-4 spacing 0.4 vs 0.3 µm). That makes the
  sky130 router pitch 1.9 µm and is why sky130 routes poorly.

### Tests

87 tests, all passing: 82 in gLayout (`tests/test_schematic.py`, `test_annotate.py`, `test_sizing.py`,
`test_graph_schema.py`, `test_to_circuit.py`, `test_graph_circuit.py`, plus your `test_finger_sequence.py`,
`test_floorplan.py`, `test_router.py`, `test_netaware_interdigitized.py`) and 5 in `learn/tests/test_data.py`.

## 5. Running the demo

Everything runs inside the iic-osic-tools container, from the project folder, with the project venv active:

```bash
cd /foss/designs/glayout-martin
```

If `klayout`, `magic` or `netgen` are not found:

```bash
export PATH=/foss/tools/klayout:/foss/tools/magic/bin:/foss/tools/netgen/bin:/foss/tools/bin:$PATH
```

### Phases 1–4 on one circuit (`glayout-work/demo_phases.py`)

| Command | Shows | Time |
|---|---|---|
| `python glayout-work/demo_phases.py 1` | AnalogGenie's raw `157.cir`, the parsed `Schematic`, and PR #127's C08 (the same circuit) | seconds |
| `python glayout-work/demo_phases.py 2` | blocks, symmetry, matched pairs, and the check against PR #127's declared pairs | seconds |
| `python glayout-work/demo_phases.py 3` | sizing, floorplan, routing, closed-loop rounds; writes `glayout-work/out/demo/demo_c08_gf180.gds` and its LVS netlist | ~15 s |
| `python glayout-work/demo_phases.py 4` | node and edge counts, one device's features; writes the graph as JSON | ~15 s |

Options: `--circuit` takes `C01`…`C18`, `two_stage_ota` or an AnalogGenie key (`ag157`, `ag2200`,
`ag2215_opamp`, …); `--pdk sky130` switches the PDK. For example:

```bash
python glayout-work/demo_phases.py 3 --circuit ag2215_opamp
```

Open the layout with gf180's layer colours:

```bash
klayout -l /foss/pdks/gf180mcuD/libs.tech/klayout/tech/gf180mcu.lyp /foss/designs/glayout-martin/glayout-work/out/demo/demo_c08_gf180.gds
```

DRC and LVS on the same circuit (a couple of minutes):

```bash
python gLayout/tests/drc/run_cell_drc.py --pdk gf180 --params gLayout/tests/parameters/schematic_gf180.csv --cells sch_c08_routed --engine both --jobs 1 --out-dir /tmp/demo_drc
```

```bash
python gLayout/tests/lvs/run_cell_lvs.py --pdk gf180 --inputs-dir /tmp/demo_drc --out-dir /tmp/demo_lvs
```

### Phase 5: the dataset

```bash
python learn/data/ingest.py
```

Parses and annotates all 4,120 items (~10 s) and prints the coverage tables (also in `learn/data/coverage.md`).

```bash
python learn/data/dedupe_split.py --check
```

Recomputes the split; prints `splits.json reproduced exactly`.

### Phase 6: labels

A small label run (two circuits, gf180, ~3 min), its report, and an audit (~5 min):

```bash
python learn/labels/run_flow.py --run demo --keys C08,ag2215_opamp --pdks gf180 --jobs 2
```

```bash
python3 learn/labels/summarize.py --run demo
```

```bash
python learn/labels/audit.py --run demo --n 2 --jobs 2
```

The records are in `learn/labels/out/demo/records.jsonl`; the pilot's report is
`learn/labels/out/pilot/summary.md`.

Process tables: `GLAYOUT_TABLES_DEPTH=1` (the demo's default) shows top-level stages only, `GLAYOUT_TABLES_DEPTH=9`
every nested stage, `GLAYOUT_TABLES=0` none.

## 6. Open decisions and next steps

| Item | Recommendation |
|---|---|
| sky130 | Correct the via3/metal-4 rules in gLayout's sky130 table (with DRC/LVS regression on existing cells) before generating sky130 labels |
| Full gf180 label run | 534 circuits × 3 sizings × 2 seeds ≈ 3,200 records, ~9.5 h on 7 workers (1×1: ~2.5 h; 3×3: ~11.5 h) |
| Phase 7 | Bundle graphs + labels, train the R-GCN outcome predictor on the external GPUs (CUDA version and scheduler needed), compare with baselines, then use its padding predictions to warm-start the closed loop |
| Later | Resistor/capacitor blocks (~1,900 drawable circuits instead of 519); porting the finger-sequence cells to the gdstk backend (gdsfactory bookkeeping is ~60 % of build time); electrical labels on the curated test set with `glayout.evaluation` |

**Known limits:** synthetic sizing (labels describe layout, not circuit performance); MOS-only circuits of at most
12 blocks; sky130 routability limited by the rule table above; building cells is the slow step.
