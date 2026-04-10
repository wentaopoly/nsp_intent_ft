#!/usr/bin/env python3
"""
Demo: run the fine-tuned NSP intent model on all 9 intent types.

Usage:
    .venv/bin/python demos/demo_all_types.py
"""

import json
import os
import sys
import time

# ---------------------------------------------------------------------------
# Path setup: make inference/ and data/ importable
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INFERENCE_DIR = os.path.join(_ROOT, "inference")
_DATA_DIR = os.path.join(_ROOT, "data")

for _d in (_INFERENCE_DIR, _DATA_DIR):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from predict import load_model, predict, extract_json  # noqa: E402
from merge_fill_values import merge_fill_values          # noqa: E402
from intent_validator import (                            # noqa: E402
    validate_full,
    validate_canonical_similarity,
)

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Intent type metadata
# ---------------------------------------------------------------------------
INTENT_META = {
    "epipe":      "E-Pipe 点对点以太网服务",
    "tunnel":     "MPLS 隧道 / SDP",
    "vprn":       "VPRN L3 VPN 服务",
    "vpls":       "VPLS 虚拟专用LAN服务",
    "ies":        "IES 互联网增强服务",
    "etree":      "E-Tree 根叶以太网服务",
    "cpipe":      "Cpipe TDM 电路仿真服务",
    "evpn-epipe": "EVPN E-Line (mpls) 服务",
    "evpn-vpls":  "EVPN VPLS (mpls) 服务",
}

# ---------------------------------------------------------------------------
# Test instructions (one per intent type)
# ---------------------------------------------------------------------------
TEST_INSTRUCTIONS = {
    "epipe": (
        "Create an E-Pipe service named 'Epipe-VLAN-1001-demo' for customer 10 "
        "with NE service ID 2001. Connect device 192.168.0.37 on port 1/2/c4/1 "
        "to device 192.168.0.16 on port 1/2/c5/1 using VLAN 1001. MTU is 1492. "
        "Use SDP 3716 and 1637."
    ),
    "tunnel": (
        "Create an MPLS tunnel from 192.168.0.16 to 192.168.0.37 with SDP ID 1637. "
        "Name it 'SDP-from-C2U16-to-C2U37'. Use BGP signaling with TLDP."
    ),
    "vprn": (
        "Create a VPRN L3 VPN service 'VPRN-100-DataCenter' for customer 5. "
        "Configure site on device 192.168.0.16 with service ID 100. "
        "Route distinguisher 65000:100. VRF import: DC-VRF-Import, VRF export: "
        "DC-VRF-Export. Interface GPU-Cluster-Compute on port 1/2/c4/1 with IP "
        "10.100.1.1/24. Interface GPU-Cluster-Storage on port 1/2/c5/1 with IP "
        "10.100.2.1/24."
    ),
    "vpls": (
        "Create a VPLS service 'VPLS-500-Campus' for customer 20, NE service ID "
        "500, MTU 1500. Site 1: device 192.168.0.16 on port 1/2/c4/1 with VLAN "
        "500. Site 2: device 192.168.0.37 on port 1/2/c5/1 with VLAN 500."
    ),
    "ies": (
        "Set up an IES service 'IES-300-Access' for customer 15 with NE service "
        "ID 300 on device 192.168.0.16. Interface AccessPort1 on port 1/2/c4/1 "
        "with IP 10.30.1.1/24. Interface AccessPort2 on port 1/2/c5/1 with IP "
        "10.30.2.1/24."
    ),
    "etree": (
        "Create an E-Tree service 'ETree-400-HubSpoke' for customer 25 with NE "
        "service ID 400, MTU 1500. Root device 192.168.0.16 on port 1/2/c4/1. "
        "Leaves: device 192.168.0.37 on port 1/2/c5/1; device 192.168.0.38 on "
        "port 1/2/c6/1. VLAN 400."
    ),
    "cpipe": (
        "Create a Cpipe TDM service 'Cpipe-600-TDM' for customer 35 with NE "
        "service ID 600. vc-type cesopsn. Site A: device 192.168.0.16, port "
        "1/2/c4/1, time-slots 1-32. Site B: device 192.168.0.37, port 1/2/c5/1, "
        "time-slots 1-32."
    ),
    "evpn-epipe": (
        "Create an mpls-EVPN E-Line service 'EVPN-Epipe-700-DC' for customer 40 "
        "with NE service ID 700 and EVI 700. Configure on device 192.168.0.16, "
        "port 1/2/c4/1, VLAN 700. Local AC 'AC-DC-local', remote AC 'AC-DC-remote'."
    ),
    "evpn-vpls": (
        "Create a mpls-EVPN VPLS service 'EVPN-VPLS-800-Campus' for customer 45 "
        "with NE service ID 800, EVI 800, MTU 1500. Site 1: 192.168.0.16 on port "
        "1/2/c4/1 with VLAN 800. Site 2: 192.168.0.37 on port 1/2/c5/1 with VLAN "
        "800."
    ),
}

# Keep a stable ordering matching the INTENT_META dict
INTENT_ORDER = list(INTENT_META.keys())

SEP = "\u2550" * 51  # ═ repeated


def _tier6_summary(intent_type, fill_values):
    """Build a human-readable Tier 6 line."""
    n_known, n_novel, novel = validate_canonical_similarity(intent_type, fill_values)
    total = n_known + n_novel
    if total == 0:
        return "N/A (no canonical payloads)"
    return f"{n_known}/{total} known" + (f"  ({n_novel} novel)" if n_novel else "")


def run_demo():
    # ------------------------------------------------------------------
    # 1. Load model once
    # ------------------------------------------------------------------
    print(f"\n{SEP}")
    print("Loading fine-tuned NSP intent model ...")
    print(f"{SEP}\n")
    t0 = time.time()
    model, tokenizer = load_model()
    print(f"\nModel loaded in {time.time() - t0:.1f}s\n")

    # Accumulate results for the summary table
    results = {}  # intent_type -> dict with status flags

    for idx, intent_type in enumerate(INTENT_ORDER, 1):
        label = INTENT_META[intent_type]
        instruction = TEST_INSTRUCTIONS[intent_type]

        print(f"\n{SEP}")
        print(f"[{idx}/9] {intent_type} \u2014 {label}")
        print(f"{SEP}")

        # ------------------------------------------------------------------
        # 2a. Predict
        # ------------------------------------------------------------------
        print(f"\n\U0001f4dd 用户指令:")
        print(f"{instruction}\n")

        t_start = time.time()
        raw_output = predict(model, tokenizer, instruction)
        elapsed = time.time() - t_start

        # ------------------------------------------------------------------
        # 2b. Extract JSON
        # ------------------------------------------------------------------
        parsed = extract_json(raw_output)
        json_ok = parsed is not None
        fill_values = parsed.get("fill_values", {}) if parsed else {}
        got_intent_type = parsed.get("intent_type", "") if parsed else ""

        print(f"\U0001f50d 模型输出 (fill_values):  [{elapsed:.1f}s]")
        if parsed:
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        else:
            print(f"  [FAILED to parse JSON from model output]")
            print(f"  Raw output: {raw_output[:500]}")

        # ------------------------------------------------------------------
        # 2c. Merge
        # ------------------------------------------------------------------
        merged = None
        api_ready = False
        if json_ok and fill_values:
            try:
                merged = merge_fill_values(got_intent_type or intent_type, fill_values)
                api_ready = merged is not None
            except Exception as exc:
                print(f"  Merge error: {exc}")

        # ------------------------------------------------------------------
        # 2d. Validate
        # ------------------------------------------------------------------
        val_ok = False
        tier_errors = {}
        if json_ok and fill_values:
            try:
                val_ok, tier_errors = validate_full(
                    got_intent_type or intent_type, fill_values, merged_json=merged
                )
            except Exception as exc:
                print(f"  Validation error: {exc}")

        t12_pass = not tier_errors.get("tier1_2", [True])
        t3_pass = not tier_errors.get("tier3", [True])
        t4_pass = not tier_errors.get("tier4", [True])

        # Tier 6 summary
        t6_str = _tier6_summary(
            got_intent_type or intent_type, fill_values
        ) if fill_values else "N/A"

        print(f"\n\u2705 验证结果:")
        print(f"  Tier 1+2 (YANG path/type): {'PASS' if t12_pass else 'FAIL'}")
        if tier_errors.get("tier1_2"):
            for e in tier_errors["tier1_2"]:
                print(f"    - {e}")
        print(f"  Tier 3 (merged structure):  {'PASS' if t3_pass else 'FAIL'}")
        if tier_errors.get("tier3"):
            for e in tier_errors["tier3"]:
                print(f"    - {e}")
        print(f"  Tier 4 (semantic rules):    {'PASS' if t4_pass else 'FAIL'}")
        if tier_errors.get("tier4"):
            for e in tier_errors["tier4"]:
                print(f"    - {e}")
        print(f"  Tier 6 (canonical match):   {t6_str}")
        if tier_errors.get("tier6_novel_paths"):
            for p in tier_errors["tier6_novel_paths"]:
                print(f"    novel: {p}")

        # ------------------------------------------------------------------
        # 2e. Print and save API-ready JSON
        # ------------------------------------------------------------------
        if merged:
            print(f"\n\U0001f4e6 NSP API-Ready JSON:")
            api_str = json.dumps(merged, indent=2, ensure_ascii=False)
            print(api_str)

            out_path = os.path.join(OUTPUT_DIR, f"{intent_type}_api_ready.json")
            with open(out_path, "w") as f:
                f.write(api_str + "\n")
            print(f"\n  -> saved to {out_path}")
        else:
            print(f"\n\U0001f4e6 NSP API-Ready JSON: [not available]")

        # Record for summary
        results[intent_type] = {
            "val_ok": val_ok,
            "json_ok": json_ok,
            "api_ready": api_ready,
        }

    # ------------------------------------------------------------------
    # 5. Summary table
    # ------------------------------------------------------------------
    print(f"\n\n{SEP}")
    print("DEMO 总结")
    print(f"{SEP}")
    print(f"  {'类型':<15s} {'验证':<8s} {'JSON有效':<11s} {'API-Ready'}")

    n_pass = 0
    for intent_type in INTENT_ORDER:
        r = results[intent_type]
        v = "\u2705" if r["val_ok"] else "\u274c"
        j = "\u2705" if r["json_ok"] else "\u274c"
        a = "\u2705" if r["api_ready"] else "\u274c"
        if r["val_ok"] and r["json_ok"] and r["api_ready"]:
            n_pass += 1
        print(f"  {intent_type:<15s} {v:<8s} {j:<11s} {a}")

    print(f"\n  全部 {n_pass}/9 通过")
    print()


if __name__ == "__main__":
    run_demo()
