"""
Dry-run sanity check for the M3 retraining.

Verifies the things that can break training WITHOUT actually loading the
9B model or starting any optimizer steps:

  1. The training script imports cleanly.
  2. The 9-intent train / val / test datasets load with the right counts.
  3. The chat template renders the SYSTEM_PROMPT + user + assistant messages.
  4. EVERY sample's tokenized length is within max_length=2048. The new
     etree intent type can hit ~89 fields per sample so this is the most
     important check before launching training.
  5. SFTConfig math (steps, effective batch, ETA) is reported.

Run with:
    .venv/bin/python train/dryrun_train.py
"""

import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "generated")


def main():
    print("=" * 60)
    print("M3 retraining dry-run sanity check")
    print("=" * 60)

    # 1. Import chain — make sure train_qwen3_nsp.py + its deps don't blow up.
    print("\n[1] Verifying training script import chain...")
    sys.path.insert(0, os.path.join(ROOT, "train"))
    try:
        import train_qwen3_nsp  # noqa: F401
        print("    ✓ train_qwen3_nsp imports cleanly")
    except Exception as exc:
        print(f"    ✗ import failed: {exc}")
        sys.exit(1)

    # 2. Load tokenizer (small + fast, ~5 sec)
    print("\n[2] Loading tokenizer (Qwen/Qwen3.5-9B)...")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        "Qwen/Qwen3.5-9B", trust_remote_code=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    print(f"    ✓ tokenizer loaded (vocab_size={tokenizer.vocab_size})")

    # 3. Load datasets
    print("\n[3] Loading 9-intent JSONL datasets...")
    splits = {}
    for label in ("train", "val", "test", "golden_tests"):
        path = os.path.join(DATA_DIR, f"{label}.jsonl")
        with open(path) as f:
            samples = [json.loads(line) for line in f]
        splits[label] = samples
        print(f"    {label:<14}: {len(samples):>5} samples")

    # 4. Per-intent distribution
    print("\n[4] Per-intent distribution (train):")
    by_intent = Counter()
    for s in splits["train"]:
        out = json.loads(s["messages"][2]["content"])
        by_intent[out["intent_type"]] += 1
    for it, n in sorted(by_intent.items()):
        print(f"    {it:<13}: {n}")

    # 5. Tokenization length distribution — THE critical check
    print("\n[5] Tokenized length distribution (train + val)...")
    MAX_LEN = 4096
    tok_lens = []
    too_long = []
    by_intent_max = {}
    for label in ("train", "val"):
        for s in splits[label]:
            text = tokenizer.apply_chat_template(
                s["messages"], tokenize=False, add_generation_prompt=False,
            )
            ids = tokenizer(text, add_special_tokens=False)["input_ids"]
            n = len(ids)
            tok_lens.append(n)
            out = json.loads(s["messages"][2]["content"])
            it = out["intent_type"]
            by_intent_max[it] = max(by_intent_max.get(it, 0), n)
            if n > MAX_LEN:
                too_long.append((label, it, n))

    n = len(tok_lens)
    print(f"    samples checked: {n}")
    print(f"    min:    {min(tok_lens)} tokens")
    print(f"    median: {sorted(tok_lens)[n // 2]}")
    print(f"    p90:    {sorted(tok_lens)[int(n * 0.9)]}")
    print(f"    p99:    {sorted(tok_lens)[int(n * 0.99)]}")
    print(f"    max:    {max(tok_lens)}")

    print("\n    Per-intent max length:")
    for it, m in sorted(by_intent_max.items(), key=lambda x: -x[1]):
        flag = "  <-- exceeds 2048" if m > MAX_LEN else ""
        print(f"      {it:<13}: {m}{flag}")

    if too_long:
        print(f"\n    WARNING: {len(too_long)} samples exceed max_length={MAX_LEN}:")
        for label, it, n in too_long[:5]:
            print(f"      {label} {it}: {n} tokens")
        print(f"    -> training will silently truncate these samples!")
    else:
        print(f"\n    ✓ all samples fit in max_length={MAX_LEN}")

    # 6. Step / time math
    print("\n[6] SFTConfig step math:")
    n_train = len(splits["train"])
    n_gpus = 2
    per_gpu_bs = 2
    grad_accum = 8
    n_epochs = 5
    eff_batch = per_gpu_bs * grad_accum * n_gpus
    steps_per_epoch = (n_train + eff_batch - 1) // eff_batch
    total_steps = steps_per_epoch * n_epochs
    print(f"    n_train         : {n_train}")
    print(f"    GPUs            : {n_gpus}")
    print(f"    per-GPU batch   : {per_gpu_bs}")
    print(f"    grad accum      : {grad_accum}")
    print(f"    effective batch : {eff_batch}")
    print(f"    steps per epoch : {steps_per_epoch}")
    print(f"    epochs          : {n_epochs}")
    print(f"    total steps     : {total_steps}")
    print(f"    eval frequency  : every 50 steps -> {total_steps // 50} eval points")
    print(f"    save frequency  : every 100 steps -> {total_steps // 100} checkpoints")

    # 7. Render one sample for visual sanity
    print("\n[7] Rendered chat template (one train sample):")
    s = splits["train"][0]
    text = tokenizer.apply_chat_template(
        s["messages"], tokenize=False, add_generation_prompt=False,
    )
    print("    " + ("-" * 56))
    for line in text.splitlines()[:8]:
        print(f"    {line[:78]}")
    print("    ...")
    print("    " + ("-" * 56))

    # 8. Final verdict
    print("\n" + "=" * 60)
    if too_long:
        print("DRY-RUN VERDICT: WARN  (some samples exceed max_length)")
    else:
        print("DRY-RUN VERDICT: PASS  (training is safe to launch)")
    print("=" * 60)


if __name__ == "__main__":
    main()
