"""Group duplicate circuits and freeze the train / validation / test split.

Run inside the container after ``ingest.py``:

    .venv/bin/python learn/data/dedupe_split.py          # writes learn/data/splits.json once
    .venv/bin/python learn/data/dedupe_split.py --check  # recompute and compare, write nothing

Rule (fixed before any training):
  1. Items are grouped when they share a Weisfeiler-Lehman topology hash (``wl.py``) or an
     AnalogGenie id (an entry and its opamp extract stay together).
  2. Test = every group holding a curated circuit: one of the 18 textbook topologies of
     gLayout PR #127 (by AnalogGenie id, or by hash, which also catches other copies) or the
     two-stage OTA of glayout.floorplan.examples. The curated netlists themselves are test
     items too (keys C01 ... C18, two_stage_ota).
  3. The other groups are shuffled with ``--seed`` per category; ``--val`` of each category's
     groups go to validation, the rest to training.
Every split is over all items; which items the v1 layout flow can draw is in each record's
summary (``layout_v1``), so netlist-only work can use the rest.

``splits.json`` is never overwritten unless ``--force`` is given.
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from wl import WL_VERSION, wl_hash

from glayout.schematic import annotate
from glayout.schematic.textbook import TEXTBOOK, curated

LEARN = Path(__file__).resolve().parents[1]
BUILD = LEARN / "data" / "build"
SPLITS = LEARN / "data" / "splits.json"


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def build_splits(records: list[dict], seed: int, val_frac: float) -> dict:
    items = {}
    for r in records:
        items[r["key"]] = {"ag_id": r["ag_id"], "variant": r["variant"], "category": r["category"],
                           "wl": wl_hash(r["schematic"]), "layout_v1": r["summary"]["layout_v1"], "source": "analoggenie"}
    cur = curated()
    curated_ids = {ag for ag, *_ in TEXTBOOK.values()}
    for key, sch in cur.items():
        ann = annotate(sch)
        items[key] = {"ag_id": sch.provenance.get("analoggenie_id"), "variant": "curated",
                      "category": "curated", "wl": wl_hash(sch.to_json()), "source": "curated",
                      "layout_v1": "ok" if sch.is_mos_only and len(ann.blocks) <= 12 else "non_mos"}
    curated_hashes = {items[k]["wl"] for k in cur}

    uf = _UF()
    by_hash, by_ag = defaultdict(list), defaultdict(list)
    for k, it in items.items():
        uf.find(k)
        by_hash[it["wl"]].append(k)
        if it["ag_id"] is not None:
            by_ag[it["ag_id"]].append(k)
    for group in list(by_hash.values()) + list(by_ag.values()):
        for k in group[1:]:
            uf.union(group[0], k)
    groups = defaultdict(list)
    for k in items:
        groups[uf.find(k)].append(k)

    def is_test(members):
        return any(items[k]["source"] == "curated" or items[k]["wl"] in curated_hashes
                   or (items[k]["ag_id"] in curated_ids and items[k]["variant"] == "main") for k in members)

    def category(members):
        main = sorted((m for m in members if items[m]["variant"] == "main"), key=lambda m: items[m]["ag_id"])
        return items[(main or sorted(members))[0]]["category"] or "unlisted"

    rng = random.Random(seed)
    per_cat = defaultdict(list)
    split_of_group = {}
    for gid, members in groups.items():
        if is_test(members):
            split_of_group[gid] = "test"
        else:
            per_cat[category(members)].append(gid)
    for cat in sorted(per_cat):
        gids = sorted(per_cat[cat], key=lambda g: min(groups[g]))
        rng.shuffle(gids)
        n_val = round(val_frac * len(gids))
        for i, g in enumerate(gids):
            split_of_group[g] = "val" if i < n_val else "train"

    names = {}
    for gid, members in groups.items():
        names[gid] = min(members, key=lambda m: (items[m]["source"] != "curated", items[m]["ag_id"] or 0, m))
    out_items = {k: {**it, "split": split_of_group[uf.find(k)], "group": names[uf.find(k)]}
                 for k, it in sorted(items.items())}
    return {
        "version": 1,
        "rule": __doc__.split("Rule (fixed before any training):")[1].split("Every split")[0].strip(),
        "wl": WL_VERSION,
        "seed": seed,
        "val_fraction": val_frac,
        "items": out_items,
        "counts": counts(out_items),
    }


def counts(items: dict) -> dict:
    c = {"items": Counter(), "groups": defaultdict(set), "layout_v1_items": Counter(), "layout_v1_groups": defaultdict(set),
         "unique_topologies": defaultdict(set)}
    for k, it in items.items():
        s = it["split"]
        c["items"][s] += 1
        c["groups"][s].add(it["group"])
        c["unique_topologies"][s].add(it["wl"])
        if it["layout_v1"] == "ok":
            c["layout_v1_items"][s] += 1
            c["layout_v1_groups"][s].add(it["group"])
    return {name: {s: (len(v) if isinstance(v, set) else v) for s, v in sorted(d.items())} for name, d in c.items()}


def leakage(items: dict) -> list[str]:
    out = []
    for field in ("wl", "group"):
        seen = defaultdict(set)
        for it in items.values():
            seen[it[field]].add(it["split"])
        out += [f"{field} {v} in {sorted(s)}" for v, s in seen.items() if len(s) > 1]
    ag = defaultdict(set)
    for it in items.values():
        if it["ag_id"] is not None and it["source"] == "analoggenie":
            ag[it["ag_id"]].add(it["split"])
    out += [f"ag {a} in {sorted(s)}" for a, s in ag.items() if len(s) > 1]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val", type=float, default=0.1)
    ap.add_argument("--force", action="store_true", help="overwrite an existing splits.json")
    ap.add_argument("--check", action="store_true", help="recompute and compare with splits.json")
    args = ap.parse_args()
    records = [json.loads(line) for line in open(BUILD / "schematics.jsonl")]
    sp = build_splits(records, args.seed, args.val)
    leaks = leakage(sp["items"])
    if leaks:
        sys.exit("leakage: " + "; ".join(leaks[:10]))
    if args.check:
        old = json.loads(SPLITS.read_text())
        same = {k: v["split"] for k, v in old["items"].items()} == {k: v["split"] for k, v in sp["items"].items()}
        print("splits.json reproduced exactly" if same else "splits.json DIFFERS from a fresh computation")
        sys.exit(0 if same else 1)
    if SPLITS.exists() and not args.force:
        sys.exit(f"{SPLITS} exists and is frozen; use --check to verify it or --force to replace it")
    sp["created"] = datetime.date.today().isoformat()
    cov = json.loads((LEARN / "data" / "coverage.json").read_text())
    sp["analoggenie_sha"] = cov.get("analoggenie_sha")
    SPLITS.write_text(json.dumps(sp, indent=1, sort_keys=True) + "\n")
    print(json.dumps(sp["counts"], indent=1))


if __name__ == "__main__":
    main()
