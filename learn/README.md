# learn: AnalogGenie → circuit graphs → layout-outcome predictor

Research code for training a model on gLayout's floorplanning flow. The netlist, annotation, sizing,
schematic → circuit and graph code it relies on is library code in gLayout (`glayout.schematic`); this
folder holds the dataset build, the label jobs and (later) training, so torch never becomes a gLayout
dependency. Plan and phase status: see the project notes.

## Data (phase 5)

| step | command (inside the iic-osic-tools container, from `/foss/designs/glayout-martin`) | output |
|---|---|---|
| fetch | `learn/data/fetch_analoggenie.sh` (git, host or container) | `learn/external/AnalogGenie` at `efc2535`, netlists only (no scans) |
| parse + annotate | `.venv/bin/python learn/data/ingest.py` | `data/build/schematics.jsonl`, `data/coverage.{json,md}` |
| de-duplicate + split | `.venv/bin/python learn/data/dedupe_split.py` (`--check` to verify) | `data/splits.json` (frozen) |
| tests | `.venv/bin/python learn/tests/test_data.py` | |

- **Items:** each AnalogGenie entry (`ag<id>`, read from `<id>_full.cir` when it exists so composite cells
  become transistors) and, for bandgap and LDO entries, their error amplifier (`ag<id>_opamp`, ports inferred
  from net names). 4120 items; see [data/coverage.md](data/coverage.md).
- **v1 layout scope:** MOS only, nfet bodies on ground, at most 12 blocks: 524 items. Supporting resistors and
  capacitors would add about 1400.
- **Split** (rule in `dedupe_split.py`, fixed before any training): items sharing a Weisfeiler-Lehman topology
  hash or an AnalogGenie id are grouped; the groups of the 18 curated textbook circuits (gLayout PR #127) and
  the two-stage OTA are the test set; the rest is 90/10 train/validation per category (seed 0).
  Train 3689 / val 413 / test 37 items (v1 layout: 462 / 51 / 26).
- **Sizing is synthetic** (`glayout.schematic.sizing`): labels from these circuits are layout labels only.
  Electrical claims use the curated test circuits, which have testbenches in PR #127.

## Licences

AnalogGenie (https://github.com/xz-group/AnalogGenie) is MIT; its netlists are used here. Its textbook scans
are the publishers' and are never downloaded.
