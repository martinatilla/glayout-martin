"""Tests for the dataset tools (learn/data). Run inside the container with the project venv:

    .venv/bin/python learn/tests/test_data.py
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("GLAYOUT_TABLES", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data"))

from dedupe_split import build_splits, leakage  # noqa: E402
from wl import wl_hash  # noqa: E402

from glayout.schematic import annotate, parse_analoggenie, textbook_schematic  # noqa: E402

AG157 = """M4 (net23 VB1 VSS VSS) nmos4
M3 (VOUT1 VIN2 net23 VSS) nmos4
M2 (net22 VIN1 net23 VSS) nmos4
M0 (net22 net22 VDD VDD) pmos4
M1 (VOUT1 net22 VDD VDD) pmos4
"""
PORTS = ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "VB1"]


def _h(text, ports=PORTS):
    return wl_hash(parse_analoggenie(text, "x", ports).to_json())


def test_names_and_order_do_not_matter():
    base = _h(AG157)
    renamed = AG157.replace("net23", "tail").replace("net22", "n9").replace("M4", "Q7")
    shuffled = "\n".join(reversed(AG157.strip().splitlines()))
    assert _h(renamed) == base and _h(shuffled) == base


def test_mos_drain_and_source_are_interchangeable():
    swapped = AG157.replace("M4 (net23 VB1 VSS VSS)", "M4 (VSS VB1 net23 VSS)")
    assert _h(swapped) == _h(AG157)


def test_curated_c08_is_its_analoggenie_entry():
    assert wl_hash(textbook_schematic("C08").to_json()) == _h(AG157)


def test_different_circuits_hash_apart():
    base = _h(AG157)
    assert _h(AG157.replace("M1 (VOUT1 net22 VDD VDD)", "M1 (VOUT1 VOUT1 VDD VDD)")) != base    # rewired
    assert _h(AG157, [p for p in PORTS if p != "VB1"]) != base                                  # port turned internal
    assert _h(AG157.replace("pmos4", "nmos4")) != base                                          # device kind
    assert wl_hash(textbook_schematic("C07").to_json()) != base


def _record(key, text, ag_id, category, variant="main", ports=PORTS):
    sch = parse_analoggenie(text, key, ports)
    return {"key": key, "ag_id": ag_id, "variant": variant, "category": category, "schematic": sch.to_json(),
            "summary": {"layout_v1": "ok", "blocks": len(annotate(sch).blocks)}}


def test_split_keeps_copies_and_extracts_together_and_curated_in_test():
    mirror = "M1 (A A VSS VSS) nmos4\nM2 (B A VSS VSS) nmos4"
    recs = [
        _record("ag157", AG157, 157, "book:razavi_analog_cmos"),                  # curated C08's entry
        _record("ag999", AG157.replace("net23", "t"), 999, "paper:opamp"),        # a copy of it elsewhere
        _record("ag1500", mirror, 1500, "paper:bandgap", ports=["VSS", "A", "B"]),
        _record("ag1500_opamp", AG157, 1500, "paper:bandgap", "opamp_extract"),   # extract, same id
    ] + [_record(f"ag{2000 + i}", mirror.replace("B A", f"B{i} A"), 2000 + i, "paper:opamp",
                 ports=["VSS", "A", f"B{i}"]) for i in range(20)]
    sp = build_splits(recs, seed=0, val_frac=0.1)
    it = sp["items"]
    assert it["ag157"]["split"] == it["ag999"]["split"] == it["C08"]["split"] == "test"
    # the extract is a C08 copy, so its parent bandgap entry follows it into test
    assert it["ag1500"]["split"] == it["ag1500_opamp"]["split"] == "test"
    assert all(it[k]["split"] == "test" for k in it if it[k]["source"] == "curated")
    assert leakage(it) == []
    again = build_splits(recs, seed=0, val_frac=0.1)
    assert json.dumps(again["items"], sort_keys=True) == json.dumps(sp["items"], sort_keys=True)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} passed")
