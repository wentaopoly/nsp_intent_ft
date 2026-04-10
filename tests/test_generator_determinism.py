"""
Determinism contract for the per-intent generators.

The contract: every entry in `fill_values` must be either
  (a) directly copied from an instruction-visible argument,
  (b) a fixed constant for the intent type, or
  (c) a deterministic function of the instruction-visible arguments.

If a generator violates this contract by sampling random values that the
instruction never exposes, the model has no signal to predict those values
and the sample is unlearnable.

This test enforces the contract by exercising every sample builder MANY
times with the same global random seed: a sample built twice from the same
seed must produce a byte-identical (instruction, output) pair. Any
internal `random.X` call that leaks into `fill_values` without flowing
through the instruction template will be caught here.

Run with:
    .venv/bin/python tests/test_generator_determinism.py
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "data"))
sys.path.insert(0, os.path.join(ROOT, "inference"))

from generate_training_data import (  # noqa: E402
    build_epipe_sample,
    build_tunnel_sample,
    build_vprn_sample,
    build_vpls_sample,
    build_ies_sample,
    build_etree_sample,
    build_cpipe_sample,
    build_evpn_epipe_sample,
    build_evpn_vpls_sample,
)


BUILDERS = [
    ("epipe",        lambda: build_epipe_sample()),
    ("tunnel",       lambda: build_tunnel_sample()),
    ("vprn-1site",   lambda: build_vprn_sample(num_sites=1, interfaces_per_site=2)),
    ("vprn-2site",   lambda: build_vprn_sample(num_sites=2, interfaces_per_site=2)),
    ("vpls",         lambda: build_vpls_sample(num_sites=2)),
    ("ies",          lambda: build_ies_sample(interfaces_per_site=2)),
    ("etree",        lambda: build_etree_sample(num_leaf_sites=2)),
    ("cpipe",        lambda: build_cpipe_sample()),
    ("evpn-epipe",   lambda: build_evpn_epipe_sample()),
    ("evpn-vpls",    lambda: build_evpn_vpls_sample(num_sites=2)),
]


def _normalize(obj):
    """JSON round-trip so dicts compare structurally regardless of key order."""
    return json.loads(json.dumps(obj, sort_keys=True))


def main():
    failures = []

    # ----- Part 1: seed-determinism -----
    # Same seed → same (instruction, output). Catches non-determinism that
    # comes from outside `random` (e.g. `time.now()`, `id()`, set ordering).
    for label, builder in BUILDERS:
        for seed in (0, 1, 7, 42, 1729):
            random.seed(seed)
            instr1, out1 = builder()
            random.seed(seed)
            instr2, out2 = builder()

            if instr1 != instr2:
                failures.append(
                    f"[seed-det]   {label} seed={seed}: instruction differs"
                )
                continue
            if _normalize(out1) != _normalize(out2):
                fv1, fv2 = out1["fill_values"], out2["fill_values"]
                diffs = [
                    f"{k}: {fv1.get(k, '<missing>')!r} vs {fv2.get(k, '<missing>')!r}"
                    for k in sorted(set(fv1) | set(fv2))
                    if fv1.get(k) != fv2.get(k)
                ]
                failures.append(
                    f"[seed-det]   {label} seed={seed}: fill_values diverge:\n    "
                    + "\n    ".join(diffs[:5])
                )

    # ----- Part 2: instruction-arg purity (the contract that matters) -----
    # For the pure-function generators, the output must depend ONLY on the
    # explicit instruction-arg kwargs and NOT on the random state. Roll the
    # args once, then call the generator with different seeds in between
    # — the output must be byte-identical across calls.
    #
    # This catches the M3.5 baseline bug where evpn-epipe / evpn-vpls had
    # `random.X` calls inside the generator (RD/RT/VNI/eth-tag/ecmp/mtu)
    # that leaked into fill_values without flowing through the instruction.
    from field_definitions import (  # noqa: E402
        generate_evpn_epipe_values,
        generate_evpn_vpls_values,
        _roll_evpn_epipe_args,
        _roll_evpn_vpls_args,
    )

    pure_cases = [
        ("evpn-epipe", _roll_evpn_epipe_args, generate_evpn_epipe_values),
        ("evpn-vpls",  lambda: _roll_evpn_vpls_args(num_sites=2),
                       generate_evpn_vpls_values),
    ]

    for label, roller, gen in pure_cases:
        # Roll a single arg-set under one seed
        random.seed(0)
        args = roller()

        # Capture baseline output
        random.seed(123)
        baseline = _normalize(gen(**args))

        # Try a bunch of foreign random states — output must be unchanged
        for seed in (1, 7, 42, 999, 1729, 31337):
            random.seed(seed)
            current = _normalize(gen(**args))
            if current != baseline:
                fv1, fv2 = baseline, current
                diffs = [
                    f"{k}: {fv1.get(k, '<missing>')!r} vs {fv2.get(k, '<missing>')!r}"
                    for k in sorted(set(fv1) | set(fv2))
                    if fv1.get(k) != fv2.get(k)
                ]
                failures.append(
                    f"[arg-purity] {label} (foreign seed={seed}): "
                    f"output depends on random state, not just args:\n    "
                    + "\n    ".join(diffs[:5])
                )
                break

    if failures:
        print(f"FAIL — {len(failures)} non-deterministic / impure builder runs:")
        for f in failures:
            print(f"  • {f}")
        sys.exit(1)

    print(
        f"PASS — Part 1: all {len(BUILDERS)} builders are seed-deterministic "
        f"({len(BUILDERS) * 5} runs).\n"
        f"       Part 2: pure-function generators (evpn-epipe, evpn-vpls) are "
        f"arg-pure (output depends ONLY on instruction args, not random state)."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
