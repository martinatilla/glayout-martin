"""Summarise a label run: outcomes, failures, timing and label distributions.

    python3 learn/labels/summarize.py --run pilot        # plain Python, no gLayout needed

Writes learn/labels/out/<run>/summary.md and prints it.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

LEARN = Path(__file__).resolve().parents[1]


def q(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p * (len(vals) - 1) + 0.5))] if vals else float("nan")


def summarize(run: Path) -> str:
    recs = [json.loads(line) for line in (run / "records.jsonl").open()]
    graphs = {json.loads(line)["graph_id"]: None for line in (run / "graphs.jsonl").open()}
    info = json.loads((run / "run.json").read_text())
    ok = [r for r in recs if r["status"] == "ok"]
    lines = [f"# Label run `{run.name}`", "",
             f"{len(recs)} records ({len(ok)} ok, {len(recs) - len(ok)} errors), {len(graphs)} graphs; "
             f"gLayout {info['meta']['glayout']['commit'][:8]}{' (dirty)' if info['meta']['glayout']['dirty'] else ''}, "
             f"flow {info['meta']['flow']['mode']}.", ""]

    lines += ["## Outcome by PDK and split", "", "| PDK | split | records | routed | unrouted | errors | routed at zero padding |",
              "|---|---|---:|---:|---:|---:|---:|"]
    cell = defaultdict(Counter)
    for r in recs:
        c = cell[(r["pdk"], r["split"])]
        c["n"] += 1
        if r["status"] != "ok":
            c["err"] += 1
        elif r["targets"]["graph"]["routed"]:
            c["routed"] += 1
            c["r0"] += r["targets"]["graph"]["routed_round0"]
        else:
            c["unrouted"] += 1
    for (pdk, split), c in sorted(cell.items()):
        lines.append(f"| {pdk} | {split} | {c['n']} | {c['routed']} ({c['routed'] / c['n']:.0%}) | {c['unrouted']} | "
                     f"{c['err']} | {c['r0']} |")

    errs = Counter((r["error"]["stage"], r["error"]["class"], r["error"]["message"][:70]) for r in recs if r["status"] != "ok")
    if errs:
        lines += ["", "## Errors", "", "| stage | class | message | records |", "|---|---|---|---:|"]
        lines += [f"| {s} | {c} | {m} | {n} |" for (s, c, m), n in errs.most_common(12)]

    unrouted = [r for r in ok if not r["targets"]["graph"]["routed"]]
    if unrouted:
        why = Counter("unreachable pins" if r["targets"]["graph"]["unreachable_pins"] else "failed nets" for r in unrouted)
        lines += ["", f"Unrouted after the closed loop: {dict(why)}."]

    def dist(name, vals, fmt="{:.2f}"):
        return f"| {name} | " + " | ".join(fmt.format(q(vals, p)) for p in (0.0, 0.25, 0.5, 0.75, 1.0)) + " |"
    routed = [r for r in ok if r["targets"]["graph"]["routed"]]
    g = lambda k: [r["targets"]["graph"][k] for r in routed]   # noqa: E731
    lines += ["", "## Label distributions (routed records)", "", "| label | min | 25% | median | 75% | max |",
              "|---|---:|---:|---:|---:|---:|",
              dist("blocks", [len(r["targets"]["block"]) for r in routed], "{:.0f}"),
              dist("area µm²", g("area_um2"), "{:.0f}"), dist("dead space", g("dead_space")),
              dist("HPWL µm", g("hpwl_um"), "{:.0f}"), dist("routed WL µm", g("wirelength_um"), "{:.0f}"),
              dist("rounds", g("rounds"), "{:.0f}"), dist("vias", g("vias"), "{:.0f}"),
              dist("block DRR scale", [b["drr_scale"] for r in routed for b in r["targets"]["block"].values()]),
              dist("net failed round 0", [float(n["failed_round0"]) for r in routed for n in r["targets"]["net"].values()])]

    bt = [r["timing"]["build_s"] for r in recs]
    ft = [r["timing"].get("flow_s", 0.0) for r in recs if "flow_s" in r["timing"]]
    lines += ["", "## Timing (per record, one worker)", "", "| step | median s | 90% s | max s | total h |", "|---|---:|---:|---:|---:|",
              f"| build (sizing + cells + graph) | {statistics.median(bt):.1f} | {q(bt, 0.9):.1f} | {max(bt):.1f} | "
              f"{sum(bt) / 3600:.2f} |",
              f"| flow (closed loop) | {statistics.median(ft):.1f} | {q(ft, 0.9):.1f} | {max(ft):.1f} | {sum(ft) / 3600:.2f} |"]
    if "seconds" in info:
        lines += ["", f"Wall time {info['seconds'] / 60:.0f} min with {info['args']['jobs']} workers."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    run = LEARN / "labels" / "out" / args.run
    text = summarize(run)
    (run / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
