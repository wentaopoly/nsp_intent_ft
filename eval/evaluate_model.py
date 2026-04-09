"""
Evaluate the fine-tuned NSP intent model on test set and golden tests.
Reports JSON validity, intent type accuracy, field recall/precision, and value accuracy.
"""

import json
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "inference"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data"))

from predict import load_model, predict, extract_json
from merge_fill_values import merge_fill_values

# Milestone 2 validators: 4-tier YANG-aware stack from data/intent_validator.py.
#
#   tier1_2  -- path validity + type/range/enum/pattern (YANG schema-shape)
#   tier3    -- merged-JSON structural checks (envelope mandatory + body
#               mandatory + list keys + max-elements)
#   tier4    -- semantic cross-field rules (SDP bidirectional, vlan match,
#               distinct devices, src != dst, etc.)
#   all_valid = tier1_2 AND tier3 AND tier4
#
# We keep the legacy `schema_valid` metric for one more eval cycle so the
# comparison stays meaningful, but it now points at the same shim that
# routes through tier1_2 + tier4 (no more regex).
from intent_validator import (
    validate_fill_values as _validate_fill_values_yang,
    validate_merged_intent as _validate_merged_intent,
    validate_semantic as _validate_semantic,
)
from validate_sample import validate_epipe_sample, validate_tunnel_sample, validate_vprn_sample


def evaluate_single(prediction_text, ground_truth):
    """Evaluate a single prediction against ground truth."""
    scores = {
        "json_valid": False,
        "intent_type_match": False,
        "field_recall": 0.0,
        "field_precision": 0.0,
        "value_accuracy": 0.0,
        "sdp_bidirectional": None,
        "schema_valid": False,    # legacy shim (now Tier 1+2+4 via validate_sample.py)
        "yang_valid": False,      # legacy alias kept for M1 baseline comparison
        "tier1_2_valid": False,   # YANG path / type / range / enum / pattern
        "tier3_valid": False,     # merged-JSON structural (mandatory + list keys)
        "tier4_valid": False,     # semantic cross-field rules
        "all_tiers_valid": False, # all three tiers AND merge succeeds
        "yang_errors": [],
        "tier_errors": {},
    }

    # 1. JSON validity
    parsed = extract_json(prediction_text)
    if parsed is None:
        return scores
    scores["json_valid"] = True

    gt = ground_truth if isinstance(ground_truth, dict) else json.loads(ground_truth)

    # 2. Intent type match
    pred_type = parsed.get("intent_type", "")
    gt_type = gt.get("intent_type", "")
    scores["intent_type_match"] = pred_type == gt_type

    # 3. Field recall and precision
    pred_fv = parsed.get("fill_values", {})
    gt_fv = gt.get("fill_values", {})

    gt_keys = set(gt_fv.keys())
    pred_keys = set(pred_fv.keys())

    if gt_keys:
        scores["field_recall"] = len(gt_keys & pred_keys) / len(gt_keys)
    else:
        scores["field_recall"] = 1.0

    if pred_keys:
        scores["field_precision"] = len(gt_keys & pred_keys) / len(pred_keys)
    else:
        scores["field_precision"] = 0.0

    # 4. Value accuracy (on matching fields)
    matching = gt_keys & pred_keys
    if matching:
        correct = 0
        for k in matching:
            if str(pred_fv.get(k)) == str(gt_fv.get(k)):
                correct += 1
        scores["value_accuracy"] = correct / len(matching)

    # 5. SDP bidirectionality (epipe only)
    if gt_type == "epipe":
        scores["sdp_bidirectional"] = check_sdp_bidirectional(pred_fv)

    # 6. Schema validation (legacy shim — now routes to Tier 1+2+4)
    if pred_type == "epipe":
        valid, _ = validate_epipe_sample(pred_fv)
    elif pred_type == "tunnel":
        valid, _ = validate_tunnel_sample(pred_fv)
    elif pred_type == "vprn":
        valid, _ = validate_vprn_sample(pred_fv)
    else:
        valid = False
    scores["schema_valid"] = valid

    # 7. Full 4-tier YANG-driven validation (Milestone 2).
    if pred_type in ("epipe", "tunnel", "vprn"):
        tier_errors = {}
        try:
            ok12, errs12 = _validate_fill_values_yang(pred_type, pred_fv)
            scores["tier1_2_valid"] = ok12
            scores["yang_valid"] = ok12  # legacy alias for M1 comparison
            scores["yang_errors"] = errs12
            tier_errors["tier1_2"] = errs12

            ok4, errs4 = _validate_semantic(pred_type, pred_fv)
            scores["tier4_valid"] = ok4
            tier_errors["tier4"] = errs4

            # Tier 3 needs the merged JSON. If merge fails, Tier 3 fails.
            try:
                merged = merge_fill_values(pred_type, pred_fv)
                ok3, errs3 = _validate_merged_intent(pred_type, merged)
            except Exception as exc:
                ok3, errs3 = False, [f"merge crashed: {exc}"]
            scores["tier3_valid"] = ok3
            tier_errors["tier3"] = errs3

            scores["all_tiers_valid"] = ok12 and ok3 and ok4
            scores["tier_errors"] = tier_errors
        except Exception as exc:
            scores["tier1_2_valid"] = False
            scores["yang_valid"] = False
            scores["yang_errors"] = [f"validator crashed: {exc}"]
            scores["tier_errors"] = {"crash": str(exc)}

    return scores


def check_sdp_bidirectional(fv):
    """Check that SDP entries have correctly swapped source/destination."""
    try:
        s0_src = fv.get("sdp[0].source-device-id", "")
        s0_dst = fv.get("sdp[0].destination-device-id", "")
        s1_src = fv.get("sdp[1].source-device-id", "")
        s1_dst = fv.get("sdp[1].destination-device-id", "")
        # Cast to bool explicitly: Python's `and` short-circuits to the
        # last operand, so without bool() this can return a string and
        # break sum() in the metric aggregation step.
        return bool(s0_src and s0_dst and s0_src == s1_dst and s0_dst == s1_src)
    except Exception:
        return False


def run_evaluation(model, tokenizer, test_file, label="Test"):
    """Run evaluation on a JSONL test file."""
    print(f"\n{'='*60}", flush=True)
    print(f"Evaluating on: {label} ({test_file})", flush=True)
    print(f"{'='*60}", flush=True)

    with open(test_file, "r") as f:
        samples = [json.loads(line) for line in f]

    all_scores = []
    intent_counts = {"epipe": 0, "tunnel": 0, "vprn": 0}
    intent_scores = {"epipe": [], "tunnel": [], "vprn": []}

    # Per-sample checkpoint file: written incrementally so a crash in the
    # final aggregation step doesn't lose all the inference work.
    checkpoint_path = os.path.join(
        os.path.dirname(test_file) if os.path.dirname(test_file) else ".",
        f"_eval_checkpoint_{label.replace(' ', '_').lower()}.jsonl",
    )
    checkpoint_f = open(checkpoint_path, "w")

    for i, sample in enumerate(samples):
        instruction = sample["messages"][1]["content"]
        gt_output = json.loads(sample["messages"][2]["content"])
        gt_type = gt_output.get("intent_type", "unknown")

        print(f"  [{i+1}/{len(samples)}] {gt_type}: {instruction[:60]}...", end=" ", flush=True)

        prediction_text = predict(model, tokenizer, instruction)
        scores = evaluate_single(prediction_text, gt_output)

        all_scores.append(scores)
        intent_counts[gt_type] = intent_counts.get(gt_type, 0) + 1
        intent_scores.setdefault(gt_type, []).append(scores)

        # Write checkpoint row (intent_type + scores) immediately.
        checkpoint_f.write(json.dumps({"i": i, "gt_type": gt_type, "scores": scores}) + "\n")
        checkpoint_f.flush()

        status = "OK" if scores["json_valid"] and scores["value_accuracy"] > 0.8 else "FAIL"
        print(f"[{status}] val_acc={scores['value_accuracy']:.2f}", flush=True)

    checkpoint_f.close()

    # Aggregate metrics
    print(f"\n--- {label} Results ---")
    n = len(all_scores)

    metrics = {
        "JSON Valid Rate": sum(s["json_valid"] for s in all_scores) / n,
        "Intent Type Accuracy": sum(s["intent_type_match"] for s in all_scores) / n,
        "Field Recall": sum(s["field_recall"] for s in all_scores) / n,
        "Field Precision": sum(s["field_precision"] for s in all_scores) / n,
        "Value Accuracy": sum(s["value_accuracy"] for s in all_scores) / n,
        "Tier 1+2 Valid (path/type)": sum(s["tier1_2_valid"] for s in all_scores) / n,
        "Tier 3 Valid (merged structure)": sum(s["tier3_valid"] for s in all_scores) / n,
        "Tier 4 Valid (semantic)": sum(s["tier4_valid"] for s in all_scores) / n,
        "All Tiers Valid": sum(s["all_tiers_valid"] for s in all_scores) / n,
    }

    # SDP check (epipe only)
    sdp_scores = [s["sdp_bidirectional"] for s in all_scores if s["sdp_bidirectional"] is not None]
    if sdp_scores:
        metrics["SDP Bidirectional (epipe)"] = sum(sdp_scores) / len(sdp_scores)

    for name, value in metrics.items():
        target = ">=95%" if "Rate" in name or "Accuracy" in name else ""
        print(f"  {name}: {value:.1%}  {target}")

    # Per-intent-type breakdown
    print(f"\n  Per-intent breakdown:")
    for itype, scores_list in intent_scores.items():
        if not scores_list:
            continue
        ni = len(scores_list)
        va = sum(s["value_accuracy"] for s in scores_list) / ni
        fr = sum(s["field_recall"] for s in scores_list) / ni
        jv = sum(s["json_valid"] for s in scores_list) / ni
        print(f"    {itype} (n={ni}): json_valid={jv:.1%}, field_recall={fr:.1%}, value_acc={va:.1%}")

    return metrics


if __name__ == "__main__":
    DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "generated")

    model, tokenizer = load_model()

    # Evaluate on test set
    test_file = os.path.join(DATA_DIR, "test.jsonl")
    test_metrics = run_evaluation(model, tokenizer, test_file, label="Test Set")

    # Evaluate on golden tests
    golden_file = os.path.join(DATA_DIR, "golden_tests.jsonl")
    golden_metrics = run_evaluation(model, tokenizer, golden_file, label="Golden Tests")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Test Value Accuracy:   {test_metrics['Value Accuracy']:.1%}")
    print(f"Golden Value Accuracy: {golden_metrics['Value Accuracy']:.1%}")
    print(f"Test JSON Valid Rate:  {test_metrics['JSON Valid Rate']:.1%}")
    print(f"Golden JSON Valid:     {golden_metrics['JSON Valid Rate']:.1%}")
