"""
Re-run model on the 17 failing samples from M2 eval and capture full diagnostics:
  - raw model output text (with no JSON parsing applied)
  - token count
  - whether output was truncated by max_new_tokens
  - which tier first fails
  - what the model actually wrote vs what was expected

Output goes to logs/m2_diagnosis.json so we can analyze without re-running.
"""

import json
import os
import sys
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "inference"))
sys.path.insert(0, os.path.join(ROOT, "data"))

from predict import load_model, SYSTEM_PROMPT, JsonStoppingCriteria
from transformers import StoppingCriteriaList
from intent_validator import validate_full
from merge_fill_values import merge_fill_values


# Indices of failing samples from M2 eval (1-based, copied from logs)
FAIL_INDICES = [2, 53, 54, 65, 70, 75, 81, 82, 90, 95, 113, 118, 131, 141, 143, 146, 149]


def predict_raw(model, tokenizer, instruction, max_new_tokens=2048):
    """Same as predict.predict() but with larger max_new_tokens AND captures token count."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]

    stopping = StoppingCriteriaList([JsonStoppingCriteria(tokenizer, input_len)])

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            top_p=0.95,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
            stopping_criteria=stopping,
        )

    generated_ids = outputs[0][input_len:]
    text = tokenizer.decode(generated_ids, skip_special_tokens=True)
    return {
        "text": text,
        "input_tokens": int(input_len),
        "output_tokens": int(len(generated_ids)),
        "hit_max": int(len(generated_ids)) >= max_new_tokens,
    }


def main():
    print("Loading model...", flush=True)
    model, tokenizer = load_model()

    test_path = os.path.join(ROOT, "data", "generated", "test.jsonl")
    with open(test_path) as f:
        all_samples = [json.loads(line) for line in f]

    fail_samples = [(idx, all_samples[idx - 1]) for idx in FAIL_INDICES]
    print(f"Re-running {len(fail_samples)} failing samples with max_new_tokens=2048...", flush=True)

    diagnoses = []
    for one_based_idx, sample in fail_samples:
        instruction = sample["messages"][1]["content"]
        gt_text = sample["messages"][2]["content"]
        gt = json.loads(gt_text)
        gt_type = gt["intent_type"]

        print(f"\n[{one_based_idx}] {gt_type}: {instruction[:70]}...", flush=True)

        # Generate with bigger max_new_tokens to detect truncation
        raw = predict_raw(model, tokenizer, instruction, max_new_tokens=2048)
        print(f"  output_tokens={raw['output_tokens']}, hit_max={raw['hit_max']}", flush=True)
        print(f"  raw[:200]: {raw['text'][:200]!r}", flush=True)

        # Try to parse the raw output
        from predict import extract_json
        parsed = extract_json(raw["text"])
        json_valid = parsed is not None

        tier_results = {"tier1_2": None, "tier3": None, "tier4": None, "all_valid": False}
        if json_valid:
            pred_fv = parsed.get("fill_values", {})
            pred_type = parsed.get("intent_type", "")
            try:
                merged = merge_fill_values(pred_type, pred_fv)
                ok, errs = validate_full(pred_type, pred_fv, merged)
                tier_results["all_valid"] = ok
                tier_results["tier1_2"] = errs.get("tier1_2", [])
                tier_results["tier3"] = errs.get("tier3", [])
                tier_results["tier4"] = errs.get("tier4", [])
            except Exception as e:
                tier_results["merge_error"] = str(e)

        diagnoses.append({
            "index": one_based_idx,
            "gt_type": gt_type,
            "instruction": instruction,
            "ground_truth_fill_values": gt.get("fill_values", {}),
            "raw_output": raw["text"],
            "input_tokens": raw["input_tokens"],
            "output_tokens": raw["output_tokens"],
            "hit_max_new_tokens": raw["hit_max"],
            "json_valid": json_valid,
            "parsed_intent_type": parsed.get("intent_type", "") if parsed else None,
            "parsed_fill_value_keys": sorted(parsed.get("fill_values", {}).keys()) if parsed else None,
            "tier_results": tier_results,
        })

    out_path = os.path.join(ROOT, "logs", "m2_diagnosis.json")
    with open(out_path, "w") as f:
        json.dump(diagnoses, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(diagnoses)} diagnoses to {out_path}")


if __name__ == "__main__":
    main()
