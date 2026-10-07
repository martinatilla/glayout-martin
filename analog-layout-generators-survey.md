# Analog code-to-layout generators: survey and gaps for gLayout

Research notes, 2026-10-07. Covers open-source and commercial systems that turn code or netlists into analog
layout, the tradeoffs they make, and what gLayout (upstream `main` plus this repo's `my-new-feature` branch) is
missing. Claims about other systems come from their papers, talks and docs; none of them were run here.
Sources are at the end.

## TL;DR

- The field has four paradigms: **procedural generators** (BAG3, laygo2, Substrate, OpenPCells, gLayout),
  **netlist-to-GDS synthesis** (ALIGN, MAGICAL, the PKU SAGERoute/PANDA flow), **structured row-based** analog
  (ALIGN's 2026 height-quantized flow, ALOE), and **learned/agentic** layers on top of those (GeniusRoute,
  PARoute2, Basso's RL floorplanner, LayoutCopilot, PANDA, Synopsys ASO.ai, Astrus).
- They converge on one pipeline: primitives with matching patterns → constraints → placer (SA, ILP or analytical,
  chosen by problem size) → grid A* router with rip-up and reroute → DRC/LVS/PEX → sometimes simulation feedback.
  This branch now has most of the geometric half.
- **Every major group names the same open problem: performance.** ALIGN's 2023 open-issues list starts with
  "automated performance constraints". PANDA (DAC 2026) loses 61% of its OTA's UGB between pre- and post-layout
  (10.84 → 4.19 MHz, under the 8 MHz target). MAGICAL 1.0 put simulation in the loop. gLayout's Python flow has
  no PEX → simulation loop.
- **The floorplanner's variants are not electrically equivalent.** The ALIGN group (TCAD, Jun 2026) shows that
  one total fin budget, split into different finger/multiplier tuples, spreads gm by 33.7% and I_D by 42.4%.
  `anneal_floorplan` picks between 2×6, 4×3 and 8×1.5 µm variants for shape alone.
- **Where gLayout already leads:** fully open signoff (klayout + magic DRC, klayout/netgen LVS) on three open
  PDKs, with no Virtuoso or Calibre. BAG3 needs Virtuoso; MAGICAL, PANDA, LayoutCopilot and the 2026 ICPI work
  validate with Calibre/Spectre on TSMC. The branch's closed router → floorplan loop goes past Basso et al., who
  list router feedback as future work.
- **Highest-value additions, in order:** (1) PEX + ngspice evaluation harness; (2) electrical descriptors on
  variants and finger sequences; (3) a constraint IR comparable to ALIGN's; (4) net classes in the router
  (symmetric/matched, width/EM, shielding); (5) ILP compaction and well/tap planning. Phase 6 (R-GCN + PPO) is
  better deferred until (1) exists ([§5, P10](#p10-phase-6-r-gcn--ppo-defer)).

---

## 1. Four paradigms

| Paradigm | Who writes what | Strength | Weakness | Examples |
|---|---|---|---|---|
| Procedural generators | Designer writes a parameterized program per cell | Exact control, reproducible, process-portable when rules are abstracted | New code per circuit; placement and routing are the designer's job | BAG2/BAG3++, laygo2, Substrate, OpenPCells, gLayout; PCells (SKILL, PyCell, KLayout) |
| Netlist-to-GDS synthesis | Tool infers hierarchy and constraints, then places and routes | No layout code per circuit; minutes or hours instead of weeks | Quality is bounded by constraint extraction; performance only partly handled | ALIGN, MAGICAL, PKU flow, OSIRIS's PnR, AnalogMaster |
| Structured / row-based | Primitives at quantized heights, placed in rows like standard cells | Regular, scalable, FinFET-friendly, easier to migrate | Area and performance cost when the circuit doesn't fit rows | ALIGN row-based (2026), ALOE/Open-ALOE (stem cells + digital PnR), abuttable analog cell libraries, OpenFASoC aux cells |
| Learned / agentic | ML guides a deterministic engine; an LLM turns intent into constraints and parameters | Captures designer heuristics; natural-language entry | Training data is scarce (NDAs); needs a reliable engine underneath | GeniusRoute, PARoute2, Basso RL floorplanner, LayoutCopilot, PANDA, ICPI on MAGICAL, gLayout LLM, Synopsys ASO.ai, Astrus |

The paradigms stack rather than compete. ALIGN has four entry points, from "no human in the loop" to "user
codifies placement and routing in Python", which is a procedural generator inside a synthesis tool. PANDA and
ICPI put an LLM on top of a synthesis engine instead of letting it draw geometry.

---

## 2. Systems

### 2.1 Comparison

| System | Origin | Input | Primitives | Placement | Routing | Constraints | PDK abstraction | Perf. loop | Signoff |
|---|---|---|---|---|---|---|---|---|---|
| **ALIGN** | UMN, TAMU, Intel (DARPA IDEA) | Unannotated SPICE | 14 parameterized primitives (DP, CM, CCP, cascode, level shifter, decap…) with CC/ID patterns; transistor and cap arrays | Enumerative SP, ILP, SA, analytical (EA global + ILP detail), chosen by problem size; GUI to edit and re-legalize | Gridded FinFET router (global + detailed, SAT option); bulk A* on Hanan grid with per-net NDRs | 37 types ([§2.2](#22-what-each-system-is-worth-borrowing-from)) | JSON abstraction of FEOL/BEOL rules; mock PDKs, sky130 | ML surrogates (SVM/MLP, GNN "PEA") as research; listed as open | Commercial in demos |
| **MAGICAL** | UT Austin (DARPA IDEA) | Netlist + design rules | Parametric device generator | Analytical + deep-learning post-placement opt.; WellGAN wells | Multi-pin A*; GeniusRoute (VAE trained on manual layouts) | Extracted: pattern matching + small-signal analysis, S³DET, graph learning | Rule file | Simulation-in-loop block synthesis (MAGICAL 1.0) | Calibre + Virtuoso ADE |
| **PKU flow / PANDA** | Peking Univ. (Yibo Lin) | Design intent text | From topology/sizing stages | Constraint-driven: symmetry, collinearity, signal/power flow | SAGERoute / 2.0: Steiner-tree wire sizing, EM, IR, symmetry, hierarchical | LLM-planned JSON per stage | n/a | PEX + post-layout sim after every attempt, fed to the LLM | Commercial |
| **BAG3++** | Berkeley BWRC → Blue Cheetah → Tenstorrent (2025) | Python generator | MOSBase / TileBase rows on a tech grid; XBase caps, resistors, fill | Designer, on tiles | Designer assigns nets to tracks | In code | Tech config + primitive plugin | Measurement managers, design scripts | Requires Virtuoso |
| **laygo2** | Hanyang (J. Han), MOSAIC | Python generator | Templates on process placement grids | Relative / on grid | On routing grids, multi-patterning aware | In code | Grids + templates | n/a | Open or commercial |
| **Substrate** | Berkeley (R. and R. Kumar) | Rust generator | Hard macros, raw shapes, PDK `mos_layout` | `AlignRect`; array, grid and nine-patch tilers | Greedy grid router incl. off-grid pin escape | In code (types) | `Pdk` trait | `Testbench` trait; sim/LVS/PEX plugins | Plugins |
| **gLayout upstream** | UMich / OpenFASoC, ReaLLMASIC | Python generator; strict-syntax text for the LLM | fet, guard ring, mimcap, resistor, bjt, via; interdigitated and ABBA macros | Designer (relative moves) | `smart_route`, C/L/straight routes | In code | `MappedPDK` (glayers + rules); sky130, gf180, ihp130 | ngspice CI in review ([PR #124](https://github.com/ReaLLMASIC/gLayout/pull/124)) | klayout/magic DRC; netgen/klayout LVS |
| **gLayout, this branch** | | + `Circuit` (instances, nets, symmetry) | + finger-sequence CC rows, diffusion shared across devices | Sequence pair + SA, DRR padding, variants, symmetry legalization | Two-layer grid bidirectional A*, MST, RRR, pin-access planning; closed loop to the floorplanner | Symmetric pairs, self-symmetric | same | none | DRC + end-to-end LVS on the routed OTA |

### 2.2 What each system is worth borrowing from

**ALIGN.** The most complete open netlist-to-GDS flow. Taped-out results include a MIMO receiver in TSMC65 39%
smaller than the manual layout at similar gain and NF, and comparator/LDO layouts in 1–10 h against 96–120 h by hand.
- *Placer chosen by problem size.* It enumerates every sequence pair when a block is small, uses ILP when
  overconstrained, SA when large, and analytical global placement with ILP detail placement. The branch notes
  that every seed reaches the same OTA floorplan: with 4 blocks, enumeration is exact and fast.
- *Constraint vocabulary* (from `align/schema/constraint.py`):
  - Placement: `Order`, `Align`, `AlignInOrder`, `Spread`, `PlaceSymmetric`, `SymmetricBlocks`, `PlaceCloser`,
    `PlaceOnBoundary`, `BlockDistance`, `HorizontalDistance`, `VerticalDistance`, `AspectRatio`, `Boundary`,
    `Floorplan`, `CompactPlacement`, `SameTemplate`, `GroupBlocks`, `GroupCaps`, `GuardRing`, `PlaceOnGrid`.
  - Routing: `SymmetricNets`, `NetPriority`, `NetConst` (shielding, criticality), `MultiConnection` (parallel
    wires), `ChargeFlow`, `DoNotRoute`, `CustomizeRoute`, `Route`, `PortLocation`.
  - Flow: `PowerPorts`, `GroundPorts`, `ClockPorts`, `DoNotIdentify`, `Generator`.

  `Circuit` has the equivalent of two of these.
- *Primitive parameters:* body contact on/off, aspect ratio, pattern (CC or ID), fins/fingers/stacking, and wire
  width inside the primitive ("3 parallel wires to reduce R").
- *Arrays:* transistor arrays report IR drop and current mismatch per pattern. Capacitor arrays trade via count
  and bandwidth against INL/DNL: spiral placement gave 15 vias and f₃dB = 993 MHz; block-chessboard variants gave
  42–429 MHz at different INL/DNL. The same group published constructive CC placement and routing for
  binary-weighted and split DACs (DATE 2022).
- *Open issues* (Sapatnekar, ISPD 2023): automated performance constraints; learning from designer constraints;
  routing; multiple PDKs and industry flows; more mature row-based placement for new technologies. Also:
  "unit structures are not arbitrarily composable."

**MAGICAL.** Fully automatic. It taped out a 1 GS/s 3rd-order CT ΔΣ modulator in TSMC 40 nm that the authors
report beats the manual layout on power, performance and area, with layout time in minutes against months.
- *Constraint extraction from the netlist:* signal-flow analysis, pattern matching, S³DET (graph-similarity
  symmetry detection), supervised and unsupervised graph learning.
- *Routing learned from manual layouts* (GeniusRoute, ICCAD 2019). Comparator offset: 480 µV manual, 2530 µV
  with the baseline router, 830 µV with ML guidance; delay and power unchanged. **Routing decides offset.**
- *Open directions* (Pan, ISPD 2022): generalized constraints, diverse circuits, RL, "go beyond GNN", and using
  layout feedback to improve constraint generation.

**PKU: PANDA, SAGERoute, LayoutCopilot.** The most active group in 2024–2026.
- PANDA (DAC 2026) splits the flow into *Skills*, each emitting a JSON artifact (`topology.json`, `sizing.json`,
  `placement_pr.json`, `pl.json`, `routing_pr.json`, `rt.json`). The LLM plans; deterministic engines execute.
  It runs PEX after every attempt and feeds the metrics back. A run takes hours; manual takes days. Its own OTA
  shows why the loop matters: UGB 10.84 MHz pre-layout, 4.19 MHz post-layout.
- SAGERoute does Steiner-tree wire sizing under EM and IR limits, plus symmetry, "with manual design
  compatibility". SAGERoute 2.0 (DATE 2024) adds hierarchy.
- LayoutCopilot (TCAD 2025) turns natural-language requests into layout script commands (TSMC 28/40 nm).

**ICPI on MAGICAL** (arXiv, Aug 2026). LLM agents (supervisor, executor, reflector, plus a persistent "design
journal") tune five exposed parameter families: net weights, placement bias, symmetry constraints, routing
priorities, wire widths. Budget: 31 extractions and 11 post-layout simulations per design. It beats Bayesian
optimization on two OTAs (FoM 1.104 vs 0.979; 1.038 vs 0.880). **Expose knobs, not geometry, to the optimizer.**

**BAG3++ / Blue Cheetah.** Generators in production: Blue Cheetah built chiplet die-to-die PHYs (BoW, UCIe) this
way, and Tenstorrent bought it in July 2025. The row/tile abstraction (MOSBase, TileBase) on a technology grid is
the portability mechanism. It still needs Virtuoso.

**Substrate.** Written in response to BAG's limits, which its thesis lists: tied to Virtuoso; few primitives for
area-constrained layout; transistor templates hard to customize; routes are net-to-track YAML with no automatic
signal routing; Python is untyped and slow for layout algorithms. Its principles: "methodology as a library" (a
gridded methodology is just one library), one component with schematic, layout and testbench views, the PDK as a
trait. The tilers (array, grid, nine-patch) check that tile sizes are compatible before placing; that is small and
easy to copy.

**laygo2.** Templates and grids. The Hanyang group had ChatGPT-4 write laygo2 placement and routing commands
interactively, from a NAND gate up to a 100 Gb/s serializer, with DRC/LVS checks. Same idea as gLayout's LLM
work: the LLM writes generator code.

**Row-based analog** (ALIGN group, TCAD, Jun 2026). Primitive heights are integer multiples of a base row height.
MLP surrogates choose the common height from predicted gm, gds, I_D and Cgg, plus a gate-resistance model
R_g = R_sh·W_f / (3·n_f·L). Placement is a MILP in three stages: row placement with well-aware attraction,
well-island extraction, tap insertion under a conductance-based coverage model. Reports up to 68.5% less
schematic-to-post-layout gap and up to 24.1% less area; ~30 s of MILP for a 10-primitive circuit.

**gLayout LLM** (Hammoud et al., 2024). Compact strict-syntax representation; 3.8B, 7B and 22B models fine-tuned
on fewer than 50 circuits. The 22B model (2 h on one A100) completes 70% of the evaluation tasks and passes
DRC/LVS on unseen 4-transistor blocks.

**Commercial**
- *Cadence Virtuoso Studio* device-level APR: grouping, pattern controls, matching-driven placement, automatic fill
  and guard rings, supply grid generation, routing with electrical controls.
- *Synopsys ASO.ai + Custom Compiler* "analog layout synthesis" (announced 19 Mar 2026): intent and constraints in,
  DRC-clean layout and floorplan out. Claims 3× faster layout and 3× fewer iterations from five pilot customers;
  limited availability from summer 2026. Separately: ML-based schematic migration and template-based layout
  migration, with TSMC.
- *Thalia AMALIA:* migration and IP reuse; device stretching, EM compliance, a "Design Pre-Trained Transformer"
  engine (v25.2, Jul 2025).
- *Astrus* ($8M, Khosla): RL + search in the AlphaGo style, starting with SerDes.
- *Maieutic Semiconductors* ($6M): analog design assistant.

### 2.3 Learned methods worth knowing

| Method | What it does | Relevance here |
|---|---|---|
| ParaGraph (NVIDIA, DAC 2020) | GNN on the schematic predicts net parasitics and device parameters; simulation error from >100% (designer guesses) to <10% | Cheap parasitic prior before PEX exists |
| PEA GNN (ALIGN, ICCAD 2020) | Predicts how a placement affects performance | Performance term in the annealer |
| GeniusRoute (ICCAD 2019) | VAE routing-region guidance learned from manual layouts | Offset 2530 → 830 µV |
| PARoute / PARoute2 (CUHK, DAC 2024 / TCAD 2025) | 3D GNN predicts post-layout performance; guidance for the router | Performance-driven routing |
| Basso et al. (arXiv 2411.15212, 2510.15387) | R-GCN + RL floorplanning; routing-aware U-Net policy; beam search; A* RRR router | The paper this branch implements; RL is Phase 6 |
| "Breaking Symmetry" (arXiv 2503.22958) | Multi-agent RL placement driven by simulation; questions symmetry-first layout | Counterpoint to symmetry as a hard rule |
| LDE-aware analytical placement | WPE, LOD and OD spacing as analytic placement terms | WPE near well edges matters in planar 130/180 nm |

### 2.4 Datasets and benchmarks

| Name | Content | Use for gLayout |
|---|---|---|
| OSIRIS (PoliMi, Jan 2026) | 87,100 DRC/LVS-clean sky130 layouts of 5 circuits (Miller, Ahuja, feed-forward, 5T OTA, low-pass filter), with pre- and post-layout AC sims; their own SP + SA + A* PnR | Same circuit family and same algorithm family as this branch. Reports parasitic scores against ALIGN and MAGICAL, so it's a direct comparison target |
| SGAnalog (Berkeley, Oct 2026) | 273 sky130 schematics from Tiny Tapeout with author testbenches; no layouts | Real netlists to test auto-annotation and the floorplanner on |
| analog-circuits-sky130 (Hugging Face) | 130k ngspice-simulated sky130 netlists | Sizing priors |
| CapBench (Apr 2026) | Multi-PDK capacitance-extraction dataset (digital designs) | Pretraining for an ML PEX surrogate |
| gLayout LLM benchmark (2024) | Tasks from 2-transistor blocks up to a ΔΣ ADC | Already in-house |

---

## 3. The tradeoffs every system makes

1. **Control vs automation.** Generators give exact control and need code per circuit; synthesis is fast and only
   as good as its constraints. Mature systems offer both (ALIGN's entry points; Substrate as a library). gLayout's
   generators plus this branch's opt-in floorplanner already form that hybrid. Keep both entry points first-class.
2. **Gridded vs gridless.** ALIGN, BAG3 and laygo2 put everything on layer-specific grids. That buys portability
   and a simple router, costs area in bulk nodes, and is unavoidable at FinFET. gLayout draws gridless from rules
   (snapped to the 2× grid); this branch's router imposes a grid only between blocks, with off-grid landing pads.
   That suits 130/180 nm, but the cost shows in the results: the inter-block pitch is via pad + spacing (1.9 µm
   in sky130), and sky130 floorplans carry 72–78% dead space. Options: non-uniform tracks at a finer pitch, or
   allowing met1/met2 between blocks.
3. **Primitive granularity.** ALIGN places primitives (a DP, a CM); MAGICAL places devices. Primitives keep
   matching inside the cell and shrink the placement problem; devices give the placer freedom. The finger-sequence
   cells are primitives in ALIGN's sense, and `bias_bank` (3 devices in one row) is a larger one.
4. **Where constraints come from.** Manual annotation → rule/pattern extraction → GNN or graph similarity → LLM.
   Accuracy matters more than the source, and both ALIGN and MAGICAL keep user overrides.
5. **Geometric proxies vs performance.** Area, HPWL, symmetry and centroid error are proxies. The systems that
   close on performance (MAGICAL 1.0, PANDA, ICPI) do it with PEX + simulation in the loop, or with surrogates
   trained on that. All of them still call performance open.
6. **Optimizer.** SA over sequence pairs is the default for small and medium problems; ILP/MILP for exact
   constraints and legalization; analytical for scale; RL mostly for transfer or guidance. ALIGN picks by size.
7. **Coupling to commercial tools.** BAG3 needs Virtuoso; MAGICAL, PANDA, ICPI and LayoutCopilot validate with
   Calibre/Spectre on TSMC. gLayout runs open end to end on three open PDKs. That is its clearest
   differentiator, and the reason an open benchmark from gLayout would matter: most published ML results can't be
   reproduced without NDAs.
8. **Language and runtime.** Substrate argues Python is too slow and untyped for layout algorithms. Here the router
   and annealer are pure Python at 0.3–1.4 s per run, which is fine; the router-inside-the-annealer flow takes
   150–460 s. If router calls inside optimization become central, profile before porting anything.

---

## 4. Where gLayout stands

✅ present · ◐ partial · ✗ missing. "Branch" = `my-new-feature`.

| Capability | Upstream | Branch | Borrow from |
|---|---|---|---|
| Device primitives (fet, ring, mimcap, resistor, bjt, via) | ✅ | ✅ | |
| 1-D common centroid with diffusion shared across devices | ◐ (interdigitated, ABBA macro) | ✅ `finger_sequence` | |
| 2-D CC transistor arrays (dispersion, multi-row) | ✗ | ✗ | ALIGN transistor arrays |
| CC capacitor arrays for DACs, with routing | ✗ | ✗ | Constructive CC P&R (DATE 2022); ALIGN spiral/chessboard |
| Primitive recognition from a netlist | ✗ | ✗ (`Circuit` by hand) | ALIGN GCN + graph matching; MAGICAL pattern matching |
| Symmetry extraction | ✗ | ✗ | S³DET; signal-flow analysis |
| Constraint vocabulary | in code | 2 kinds | ALIGN's 37 |
| Block shape variants | ✗ | ✅ | |
| Electrical descriptors on variants | ✗ | ✗ | Row-based MLP surrogate; R_g model |
| Placement: sequence pair + SA | ✗ | ✅ with DRR | |
| Placement: exact enumeration, ILP legalization, compaction | ✗ | ✗ | ALIGN placers |
| Well islands and tap planning | ✗ (ring per cell) | ✗ | Row-based MILP + conductance tap model |
| Inter-block router (A*, MST, RRR, pin access) | ✗ | ✅ | |
| Router → placer feedback | ✗ | ✅ closed loop | (ahead of Basso et al.) |
| Symmetric / matched routing | ✗ | ✗ | ALIGN `SymmetricNets`; GeniusRoute |
| Wire sizing, EM, IR | ✗ | ✗ (via-pad width everywhere) | SAGERoute; ALIGN `MultiConnection` |
| Shielding, net priority, per-net NDR | ✗ | ✗ | ALIGN `NetConst`, `NetPriority`; bulk-router NDRs |
| Power grid generation | ✗ | ✗ | Virtuoso APR; ALIGN |
| Fill / density | ✗ | ✗ | BAG3 XBase fill; Virtuoso auto-fill |
| DRC / LVS with open tools, 3 PDKs | ✅ | ✅ (+ runner fixes) | (gLayout leads) |
| PEX | ◐ `run_pex.sh`, sky130 only | ◐ | |
| Simulation in the loop | ◐ ngspice CI in review | ✗ | MAGICAL 1.0; PANDA; ICPI |
| Performance surrogate | ✗ | ✗ | ParaGraph; PEA |
| LLM interface | ✅ strict syntax + fine-tuning | | PANDA skills/JSON; ICPI knobs |
| Typed circuit graph export | ✗ | ✅ | |
| Benchmark harness | DRC/LVS CI | ✅ `framework_benchmark.py` | OSIRIS |

Upstream activity (Jul–Sep 2026) is hardening: LVS and DRC fixes, mimcap, narrow-device dogbones, the gdstk
backend, ngspice CI. Nothing upstream overlaps the placement, routing or constraint work above.

---

## 5. What to add, in priority order

### P1. Evaluation harness: PEX + ngspice on any generated layout

**Why.** It is the open issue in ALIGN's and MAGICAL's own retrospectives, and PANDA's numbers show the size of
the gap. Without it, every later choice (variant, finger sequence, wire width, RL reward) optimizes proxies. It
also turns gLayout's open toolchain into a result: post-layout numbers that anyone can reproduce.

**How it fits.** Magic extraction exists ([verification/run_pex.sh](gLayout/src/glayout/verification/run_pex.sh),
sky130 only) and upstream ngspice CI is in review. Add `evaluate(component, circuit, testbench) -> metrics`: magic
`ext2spice` with parasitics for gf180 and sky130, the extracted subckt dropped into a testbench, pre- and
post-layout metrics and their gap returned, printed as a `ProcessTable`. Start with the routed two-stage OTA:
gain, UGB, phase margin, offset (Monte Carlo later).

**Measure.** Pre/post-layout gap per flow (no DRR, DRR, closed loop). That turns the area/HPWL table in
[floorplanning-framework-changes.md §6](floorplanning-framework-changes.md) into a performance table.

### P2. Electrical descriptors on variants and finger sequences

**Why.** One fin budget, different (fin, n_f, m) tuples: gm spread 33.7%, I_D 42.4% (row-based paper). `Variant`
records a bounding box and pins ([floorplan/block.py](gLayout/src/glayout/floorplan/block.py)), and the annealer
chooses variants for area, HPWL and aspect ratio. By the paper's R_g model, the diff pair at 8×1.5 µm has
16× lower gate resistance than at 2×6 µm, along with different drain junction capacitance and LOD stress.

**How.** Per variant, compute from geometry: R_g, drain and source AD/PD (the finger-sequence code already counts
drain regions per finger), optionally gm, gds and Cgg from an ngspice operating-point run per variant. Then add an
optional electrical term to the anneal cost, or prune variants outside a designer bound. In `SequenceWeights`
([placement/finger_sequence/search.py:33](gLayout/src/glayout/placement/finger_sequence/search.py:33)) add drain-cap
and R_g terms next to `drain_contacts`.

### P3. Constraint IR

**Why.** Every stage and every agent needs one interface. ALIGN has 37 constraint types, and PANDA passes everything
through JSON artifacts. `Circuit` has `symmetric_pairs` and `self_symmetric`
([floorplan/circuit.py:49](gLayout/src/glayout/floorplan/circuit.py:49)).

**How.** A serializable constraint list on `Circuit`. First: `Order`, `Align`, `BlockDistance` (proximity),
`GroupBlocks`, `SymmetricNets`, `NetPriority`, `NetConst` (shield, criticality), `MultiConnection` (width),
`PortLocation`, `PowerPorts`/`GroundPorts`. Reuse ALIGN's names where the meaning matches, so ALIGN-annotated
examples can be imported. The annealer takes placement constraints as penalties or legalization (as it already
does for symmetry); the router takes net constraints (P4). The same JSON is what the LLM emits (P8).

### P4. Router net classes

**Why.** Routing set comparator offset in GeniusRoute (480 vs 2530 µV). This router treats all nets alike and
draws at via-pad width ([floorplan/router.py:30](gLayout/src/glayout/floorplan/router.py:30)).

**How**, in rising effort:
1. Per-net width and track count (`MultiConnection`) from a current spec, checked against per-layer current
   density limits from the PDK's EM rules. Supply nets get wider or parallel tracks.
2. Net priority and preferred layers in the existing net-ordering step.
3. Symmetric routing for `SymmetricNets`: route one net, mirror it about the axis (the annealer already puts
   symmetric blocks on the vertical centre line), reserve the mirrored nodes, and rip up as a pair. Equal length
   and via count as a check.
4. Shielding: reserve the neighbouring tracks for a shield net (VSS) under `NetConst(shield)`.

### P5. Exact placement for small blocks, ILP compaction, well/tap planning

**Why.** Dead space after the closed loop is 42.7% (gf180) and 71.6% (sky130). ALIGN compacts with ILP after
global placement and enumerates sequence pairs outright for small blocks. The row-based MILP adds well-island
clustering and a tap-coverage model. gLayout puts a full tie ring around every cell, which costs area and is part
of why ζ is 0.7 µm (half the gf180 nwell spacing).

**How.** After SA: fix the sequence-pair topology and solve an LP/ILP for coordinates minimizing area + HPWL,
subject to non-overlap, DRR keepouts and symmetry (as equalities). PuLP or OR-Tools install from pip. Later,
merge same-type wells across neighbouring cells and replace per-cell rings with shared taps.

### P6. Automatic annotation and symmetry extraction

**Why.** It turns "write a `Circuit` by hand" into netlist-in. ALIGN and MAGICAL both depend on it.

**How.** Start rule-based on the typed graph from `Circuit.graph()`: subgraph isomorphism (networkx VF2) against a
primitive library (DP, CM, CCP, cascode, diode load) that maps onto existing cells; symmetry by pairing devices
with equal W/L whose neighbourhoods are isomorphic under a net swap (the S³DET idea). Test on SGAnalog's sky130
netlists. An LLM can propose annotations; rule checks should confirm them.

### P7. 2-D common-centroid arrays (transistors and capacitors)

**Why.** SAR ADCs and current-steering DACs need them, and `finger_sequence` is 1-D.

**How.** Extend `FingerSequence` to a list of rows with 2-D centroid, second-moment and dispersion metrics; draw
each row with `finger_sequence_row` and share gate and rail routing between rows. For capacitors, the constructive
CC placement and trunk routing of the DATE 2022 paper is a well-defined target on top of `mimcap`.

### P8. Agentic LLM layer over the IR, not over geometry

**Why.** The 2024 gLayout LLM writes layout code, as does the laygo2 work. PANDA and ICPI split it better: the LLM
plans constraints and parameters, deterministic engines draw. ICPI beat BO with 31 extractions per design by
tuning five parameter families.

**How.** Expose tools: build cell, set constraint, anneal, route, evaluate (P1). Observations come from the
`ProcessTable` output (already structured) and the provenance tool (shape → code). Keep a run journal per design.
This is also an MCP-style surface for any model.

### P9. Public benchmark

**Why.** OSIRIS is the only open layout benchmark with paired post-layout performance. It includes a 5T OTA and a
Miller OTA in sky130 and reports parasitic scores against ALIGN and MAGICAL, so this flow can be compared on the
same circuits.

**How.** Extend [framework_benchmark.py](glayout-work/framework_benchmark.py) to OSIRIS's five circuits and publish
DRC/LVS/PEX and metrics for gf180 and sky130.

### P10. Phase 6 (R-GCN + PPO): defer

- The current search space is small (4 blocks, 11 variants, every seed converges). SA or enumeration is already
  near-optimal there. RL's advantage in Basso et al. is fast inference and transfer, which needs many circuits to
  show up.
- A reward built from area, HPWL and routability repeats what the annealer already optimizes. With P1, the reward
  can include post-layout performance, which is where learned methods have shown gains (PEA, PARoute2).
- SA plus the closed loop is a good data generator, as planned, but the data should carry P1's metrics.

Suggested order: P1 → P2 and P3 → P9 (larger benchmark) → RL if SA stops scaling.

---

## 6. Open problems

- **Performance-aware layout across circuit classes.** Every group lists it; nobody has a general answer. ALIGN
  notes that each class has its own metrics and unit structures don't compose freely.
- **Learning from designer layouts without NDA data.** Open PDKs plus gLayout's open signoff could produce the
  first sizable open set of layouts with post-layout metrics.
- **Matching-aware routing:** offset and mismatch from routing asymmetry, via counts, and EM on analog nets.
- **Layout-dependent effects in open planar PDKs.** WPE near well edges and LOD/STI stress. Worth checking whether
  the open sky130/gf180 models carry these parameters, and how far they move a CC row, before investing.
- **Sizing–layout co-optimization.** The two existing patterns are the row-based paper's height selection and BAG's
  generators with measurement managers.
- **Trustworthy LLM steps.** Every LLM output needs a deterministic check. SGAnalog found sharp accuracy drops
  from small to medium circuits even for the best models.

---

## Sources

**ALIGN**
- [ALIGN: A System for Automating Analog Layout (arXiv 2008.10682)](https://arxiv.org/abs/2008.10682)
- [Sapatnekar, "The ALIGN Automated Analog Layout Engine: Progress, Learnings, and Open Issues", ISPD 2023 slides](https://ispd.cc/ispd2026/slides/2023/protected/ISPD2023-Session-05/5_4_SachinSapatnekar.pdf)
- [ALIGN-public on GitHub (constraint schema in `align/schema/constraint.py`)](https://github.com/ALIGN-analoglayout/ALIGN-public)
- [Gebru et al., Row-Based Layout Synthesis for Analog Circuits Using Height-Quantized Primitives (arXiv 2606.21767)](https://arxiv.org/abs/2606.21767)
- [Constructive Common-Centroid Placement and Routing for Binary-Weighted Capacitor Arrays (DATE 2022)](https://past.date-conference.com/proceedings-archive/2022/html/0504.html)
- [Constructive Placement and Routing for Common-Centroid Capacitor Arrays in Binary-Weighted and Split DACs](https://experts.umn.edu/en/publications/constructive-placement-and-routing-for-common-centroid-capacitor-/)

**MAGICAL**
- [MAGICAL: Machine Generated Analog IC Layout (IEEE CEDA)](https://ieee-ceda.org/node/1735)
- [Pan, "Integrating Human and Machine Intelligence into Analog Routing", ISPD 2022 slides](https://ispd.cc/ispd2027/slides/2022/protected/14_5_Pan.pdf)

**PKU / CUHK / LLM flows**
- [PANDA (arXiv 2606.15052, DAC 2026)](https://arxiv.org/abs/2606.15052)
- [Simulation-Aware In-Context Policy Improvement for LLM-Aided Analog Layout Refinement (arXiv 2608.13767)](https://arxiv.org/abs/2608.13767)
- [LayoutCopilot (arXiv 2406.18873)](https://arxiv.org/abs/2406.18873)
- [AnalogMaster (arXiv 2604.20916)](https://arxiv.org/abs/2604.20916)
- [PARoute (DAC 2024)](https://www.cse.cuhk.edu.hk/~byu/papers/C223-DAC2024-PARoute.pdf)
- [PARoute2 (TCAD 2025)](https://doi.org/10.1109/TCAD.2025.3550445)
- [Basso et al., Advancing Routing-Awareness in Analog ICs Floorplanning (arXiv 2510.15387)](https://arxiv.org/abs/2510.15387)
- [Basso et al., Effective Analog ICs Floorplanning with Relational GNNs and RL (arXiv 2411.15212)](https://arxiv.org/abs/2411.15212)
- [Breaking Symmetry: multi-agent RL analog placement (arXiv 2503.22958)](https://arxiv.org/abs/2503.22958)

**Generators**
- [BAG: A Designer-Oriented Framework for AMS Circuit Generators (EECS-2014-195)](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2014/EECS-2014-195.html)
- [BAG3++ documentation](https://bag3-readthedocs.readthedocs.io/)
- [laygo2 (PyPI)](https://pypi.org/project/laygo2)
- [Kumar, A Composable Mixed-Signal Generator Framework (Substrate), EECS-2023-137](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2023/EECS-2023-137.pdf)
- [OpenPCells (P. Schulz)](https://www.github.com/patrickschulz)
- [You et al., Interactive and Automatic Generation of Primitive Custom Circuit Layout Using LLMs (arXiv 2408.07279)](https://arxiv.org/abs/2408.07279)
- [Hammoud et al., Human Language to Analog Layout Using Glayout Layout Automation](https://research.google/pubs/human-language-to-analog-layout-using-glayout-layout-automation-2/)
- [gLayout upstream (ReaLLMASIC)](https://github.com/ReaLLMASIC/gLayout)

**Learned models, LDEs**
- [ParaGraph (NVIDIA, DAC 2020)](https://research.nvidia.com/publication/2020-07_paragraph-layout-parasitics-and-device-parameter-prediction-using-graph-neural)
- [Layout-dependent-effects-aware analytical analog placement (IEEE)](https://ieeexplore.ieee.org/document/7167374)

**Datasets**
- [OSIRIS (arXiv 2601.19439)](https://arxiv.org/abs/2601.19439) · [dataset](https://huggingface.co/datasets/hardware-fab/osiris)
- [SGAnalog (arXiv 2610.03934)](https://arxiv.org/abs/2610.03934)
- [analog-circuits-sky130 (Hugging Face)](https://huggingface.co/datasets/pphilip/analog-circuits-sky130)
- [CapBench (arXiv 2604.11202)](https://arxiv.org/abs/2604.11202)

**Commercial**
- [Cadence: APR, Automated Place and Route for Virtuoso Studio](https://community.cadence.com/cadence_blogs_8/b/cic/posts/apr-automated-place-and-route-for-virtuoso-studio)
- [Cadence introduces AI-powered Virtuoso Studio](https://www.everythingrf.com/news/details/16312-cadence-introduces-ai-powered-virtuoso-studio-for-analog-custom-and-rfic-design)
- [Synopsys: AI-Powered Analog Layout Synthesis (19 Mar 2026)](https://www.synopsys.com/blogs/chip-design/analog-layout-synthesis-ai.html)
- [Synopsys: Accelerating Analog Design Migration](https://www.synopsys.com/blogs/chip-design/analog-circuit-design-migration.html)
- [Tenstorrent acquires Blue Cheetah](https://tenstorrent.com/vision/tenstorrent-acquires-blue-cheetah-analog-design)
- [Thalia enhances AMALIA platform](https://www.design-reuse.com/news/57779/thalia-enhances-amalia-platform.html)
- [Astrus](https://www.astrus.ai/)
- [Nikkei: Maieutic Semiconductors raises $6M](https://asia.nikkei.com/business/startups/indian-startup-taps-generative-ai-to-speed-up-analog-chip-design)
