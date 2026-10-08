# Quick start

Everything runs in the iic-osic-tools container (the VM desktop and its terminal); the Mac has no EDA
tools. `~/eda/designs/glayout-martin` on the Mac is `/foss/designs/glayout-martin` in the container.

## Every new terminal

```bash
cd /foss/designs/glayout-martin
unset PYTHONPATH              # the container points it at Python 3.12 packages; the venv is 3.10
source .venv/bin/activate
sak-pdk gf180mcuD             # gf180 for this terminal only (the container default is ihp-sg13g2)
```

- Without `unset PYTHONPATH`, `import glayout` dies with `AssertionError: SRE module mismatch`.
  Activating the venv does not clear it.
- One-off alternative to activating: `.venv/bin/python -E script.py` (`-E` ignores `PYTHON*` variables).
- `sak-pdk` changes only the current terminal; `sak-pdk sky130A` for sky130. In a script (no alias)
  use `source sak-pdk-script.sh gf180mcuD`. Don't put it in `/foss/designs/.designinit`: that would
  switch every project in `/foss/designs`, and the labs use IHP.

## Scripts (run from the repo root)

| Command | What it does | Output |
|---------|--------------|--------|
| `python glayout-work/simple_ota.py` | Route the 5T OTA (gf180), magic DRC | `out/simple_ota/ota5t_routed.gds` + `.spice` |
| `python glayout-work/evaluate_ota5t.py` | Build, LVS, kpex extraction, ngspice on schematic / devices / pex | `out/evaluate_ota5t/`, `results/evaluate_ota5t_gf180.json` |
| `python glayout-work/framework_benchmark.py --pdk gf180` | Mirror comparison, DRR ablation, routing benchmark (`--skip-in-loop` is faster) | `results/framework_benchmark_<pdk>.json` |
| `python glayout-work/generated_cmirror.py` | `cc_current_mirror`, 4 and 2 fingers | `out/generated_cmirror/` |
| `python glayout-work/generated_diffpair.py` | `diff_pair`, 1 and 2 fingers | `out/generated_diffpair/` |
| `python glayout-work/simple_cmirror.py` | Hand-built current mirror (sky130) | `out/simple_cmirror/` |

`evaluate_ota5t.py` options: `--seed 0 --ibias 20e-6 --cl 1e-12 --corner typical --workdir <dir>`.

Paths are under `glayout-work/`:

- `out/`: everything a script regenerates (gitignored), one folder per script. Every `<cell>.gds`
  has its LVS schematic `<cell>.spice` next to it (`write_lvs_netlist` from `glayout.evaluation`).
- `results/`: small JSON summaries, tracked.
- `reference/`: GDS kept on purpose, see its README.

Quieter output: `GLAYOUT_TABLES=0` (no process tables) or `GLAYOUT_TABLES_DEPTH=1` (top-level only).

## Tests

pytest is not in the venv; run the files directly:

```bash
python gLayout/tests/test_evaluation.py
python gLayout/tests/test_router.py
python gLayout/tests/test_floorplan.py
```

## KLayout

A GDS carries no PDK: KLayout uses whatever technology it is given. After `sak-pdk gf180mcuD`:

```bash
klayout -n gf180mcu glayout-work/out/simple_ota/ota5t_routed.gds
```

From a terminal without `sak-pdk`:

```bash
GF_PDK_OPTION=D klayout -nn /foss/pdks/gf180mcuD/libs.tech/klayout/tech/gf180mcu.lyt <file.gds>
```

Don't double-click GDS files on the desktop: they open as IHP sg13g2 (KLayout's saved default), and
the DRC menu then runs IHP rules (the MIM/NBL "violations" mean nothing on gf180).

### LVS in the GUI

1. After `sak-pdk gf180mcuD`, open any GDS under `out/`:
   ```bash
   klayout -n gf180mcu glayout-work/out/simple_ota/ota5t_routed.gds
   ```
2. **gf180mcu PDK** menu, **Run Klayout LVS**. With **Netlist Path** empty it reads `<gds name>.spice`
   (or `.cdl`) from the GDS's folder; or paste the full path of that `.spice` into Netlist Path, e.g.
   `/foss/designs/glayout-martin/glayout-work/out/simple_ota/ota5t_routed.spice`. Deep and flat
   both match on every gf180 output (variant D).
3. Results open in the netlist browser. To view the harness's earlier results without re-running:
   **Tools → Netlist Browser**, open `out/evaluate_ota5t/lvs/ota5t_routed.lvsdb`.

The `.spice` next to each GDS is the cell's `info["netlist"]` converted for KLayout (`M` devices, `u`
units, top subckt named after the cell). The netlist `simple_ota.py` prints is the raw form and fails
gf180 LVS, even with "translate schematic" on. `simple_cmirror.spice` (sky130) is only renamed: it is
the form gLayout's netgen LVS reads, untested with KLayout.

**Netlist Path is one setting for every project** (`~/.config/klayout_gf180mcu/lvs_options.yml`):
a value left over from another project wins over the netlist next to your GDS. Leave it empty, or point
it at a netlist *file*. A folder there fails with `IsADirectoryError` in the terminal and only
`Script returned a non-zero exit status (1)` in the GUI.

## From the Mac terminal

`docker exec ... bash -c` gets no tool PATH and no `PDK_ROOT` (and no `PYTHONPATH`):

```bash
docker exec -w /foss/designs/glayout-martin iic-osic-tools_xvnc_uid_501 bash -c 'export PATH=/foss/tools/klayout:/foss/tools/bin:$PATH PDK_ROOT=/foss/pdks; .venv/bin/python glayout-work/evaluate_ota5t.py'
```

With `bash -lc` instead, `unset PYTHONPATH` first (a login shell sets it).

## Gotchas

- kpex 0.4.4 needs workarounds (extracted-netlist path, substrate name, capacitance-only mode). The
  evaluation harness applies them; see `gLayout/src/glayout/evaluation/extract.py` before running
  kpex by hand.
- The harness and the scripts need `klayout`, `kpex` and `ngspice` on PATH and `PDK_ROOT` set; a VM
  terminal has all of them.
