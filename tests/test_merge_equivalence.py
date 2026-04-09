"""
Regression test for the YANG-driven `merge_fill_values` (Milestone 2).

Compares the output of the new `inference.merge_fill_values.merge_fill_values`
(YANG-driven path resolution + skeleton overlay) against the legacy version
captured from git at commit 2afc39e (saved here as `_legacy_merge_fill_values.py`).

Both implementations are run on the same set of fill_values samples drawn
from the project's actual training/validation/test/golden data, and the
resulting JSON dicts are compared for byte-for-byte equality.

If any sample produces a different result, the diff is printed and the
test exits with non-zero status. The new implementation MUST be a strict
drop-in replacement for the existing 3 intent types (epipe, tunnel, vprn)
before the legacy code can be deleted.

Run with:
    .venv/bin/python tests/test_merge_equivalence.py
"""

import json
import os
import random
import sys

# Make project root importable so we can import both versions side by side.
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "inference"))
sys.path.insert(0, HERE)  # for the legacy module copy

# Import the new version (under test)
import importlib
new_mod = importlib.import_module("merge_fill_values")
new_merge = new_mod.merge_fill_values

# Import the legacy version
legacy_mod = importlib.import_module("_legacy_merge_fill_values")
legacy_merge = legacy_mod.merge_fill_values


DATA_DIR = os.path.join(PROJECT_ROOT, "data", "generated")


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def diff_dicts(a, b, path=""):
    """Yield (path, a_value, b_value) for every difference between a and b."""
    if type(a) != type(b):
        yield (path, type(a).__name__, type(b).__name__)
        return
    if isinstance(a, dict):
        keys = set(a) | set(b)
        for k in sorted(keys):
            sub = f"{path}.{k}" if path else k
            if k not in a:
                yield (sub, "<missing>", b[k])
            elif k not in b:
                yield (sub, a[k], "<missing>")
            else:
                yield from diff_dicts(a[k], b[k], sub)
    elif isinstance(a, list):
        if len(a) != len(b):
            yield (f"{path}.<length>", len(a), len(b))
        for i, (xa, xb) in enumerate(zip(a, b)):
            yield from diff_dicts(xa, xb, f"{path}[{i}]")
    else:
        if a != b:
            yield (path, a, b)


_LEGACY_TYPES = {"epipe", "tunnel", "vprn"}


def run_one(sample, source_label):
    """Extract fill_values from a JSONL sample, merge with both versions, compare.

    Skips intent types not supported by the legacy implementation. The legacy
    `inference/merge_fill_values.py` snapshot only knows epipe / tunnel / vprn,
    so M3-introduced types (vpls / ies / etree / cpipe / evpn-epipe / evpn-vpls)
    have nothing to compare against and are filtered out by the caller.
    """
    out = json.loads(sample["messages"][2]["content"])
    intent_type = out["intent_type"]
    fv = out["fill_values"]

    legacy_result = legacy_merge(intent_type, fv)
    new_result = new_merge(intent_type, fv)

    diffs = list(diff_dicts(legacy_result, new_result))
    return intent_type, diffs, fv


def main():
    rng = random.Random(42)

    test_inputs = []

    def _is_legacy_type(s):
        out = json.loads(s["messages"][2]["content"])
        return out.get("intent_type") in _LEGACY_TYPES

    # ALL golden tests for the 3 legacy types
    golden_path = os.path.join(DATA_DIR, "golden_tests.jsonl")
    for s in load_jsonl(golden_path):
        if _is_legacy_type(s):
            test_inputs.append(("golden", s))

    # ALL test set samples for the 3 legacy types
    test_path = os.path.join(DATA_DIR, "test.jsonl")
    test_samples = [s for s in load_jsonl(test_path) if _is_legacy_type(s)]
    for s in test_samples:
        test_inputs.append(("test", s))

    # Random sample of 50 train samples per legacy intent type for breadth
    train_path = os.path.join(DATA_DIR, "train.jsonl")
    train_samples = load_jsonl(train_path)
    by_type = {"epipe": [], "tunnel": [], "vprn": []}
    for s in train_samples:
        out = json.loads(s["messages"][2]["content"])
        it = out["intent_type"]
        if it in by_type:
            by_type[it].append(s)
    for it, items in by_type.items():
        rng.shuffle(items)
        for s in items[:50]:
            test_inputs.append((f"train-{it}", s))

    n_golden = sum(1 for label, _ in test_inputs if label == "golden")
    print(f"Running {len(test_inputs)} samples through legacy and new merge...")
    print(f"  golden (legacy types only): {n_golden}")
    print(f"  test (legacy types only):   {len(test_samples)}")
    print(f"  train-epipe: 50")
    print(f"  train-tunnel: 50")
    print(f"  train-vprn:  50")

    n_total = 0
    n_pass = 0
    n_fail = 0
    fail_examples = []
    by_intent = {"epipe": {"n": 0, "pass": 0}, "tunnel": {"n": 0, "pass": 0}, "vprn": {"n": 0, "pass": 0}}

    for source, sample in test_inputs:
        n_total += 1
        try:
            intent_type, diffs, fv = run_one(sample, source)
        except Exception as exc:
            n_fail += 1
            fail_examples.append((source, "<crash>", str(exc), {}))
            continue

        by_intent[intent_type]["n"] += 1
        if not diffs:
            n_pass += 1
            by_intent[intent_type]["pass"] += 1
        else:
            n_fail += 1
            if len(fail_examples) < 5:
                fail_examples.append((source, intent_type, diffs, fv))

    print(f"\n=== Diff equivalence results ===")
    print(f"  total:  {n_total}")
    print(f"  passed: {n_pass}")
    print(f"  failed: {n_fail}")
    for it, stats in by_intent.items():
        if stats["n"]:
            print(f"    {it}: {stats['pass']}/{stats['n']}")

    if fail_examples:
        print(f"\n=== Up to 5 failure examples ===")
        for src, it, diffs, fv in fail_examples:
            print(f"\n[{src}] {it}: {len(diffs) if isinstance(diffs, list) else 'crash'} diffs")
            if isinstance(diffs, list):
                for d in diffs[:8]:
                    print(f"  {d}")
                if len(diffs) > 8:
                    print(f"  ... ({len(diffs)-8} more)")
            else:
                print(f"  exception: {diffs}")
            print(f"  fill_values keys: {sorted(fv.keys())[:6]}...")

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
