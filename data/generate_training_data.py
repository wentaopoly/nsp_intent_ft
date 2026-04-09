"""
Generate synthetic training data for NSP intent fine-tuning.
Produces JSONL files with chat-format samples for SFTTrainer.
"""

import json
import random
import os
import sys

from field_definitions import (
    generate_epipe_values, generate_tunnel_values, generate_vprn_values,
    random_project_name,
)
from instruction_templates import (
    EPIPE_TEMPLATES, TUNNEL_TEMPLATES,
    VPRN_TEMPLATES_1SITE, VPRN_TEMPLATES_2SITE,
    format_interfaces_desc,
)
from validate_sample import validate_sample

SYSTEM_PROMPT = (
    "You are an NSP (Network Services Platform) intent configuration assistant. "
    "Convert each natural language network service request into a single JSON object with three fields:\n"
    "- intent_type: one of \"epipe\", \"tunnel\", \"vprn\"\n"
    "- template_name: the NSP template name\n"
    "- fill_values: a flat dictionary of dot-notation field paths and their values\n"
    "\n"
    "Use dot notation for nested paths and [N] for list indices. Each intent type has its own naming "
    "convention -- match exactly the field paths shown in the training examples for that intent type. "
    "Only include fields that differ from template defaults.\n"
    "\n"
    "CRITICAL OUTPUT RULES:\n"
    "1. Your entire response must be a single JSON object and absolutely nothing else.\n"
    "2. Do NOT write any preamble, reasoning, plan, or explanation.\n"
    "3. Do NOT begin with phrases like \"The user wants\", \"Let me\", \"I will\", \"Sure\", \"Here is\", or \"Field paths to fill\".\n"
    "4. Do NOT wrap the JSON in markdown code fences such as ```json.\n"
    "5. Begin your response with the character `{` immediately and end it with `}`."
)


def build_epipe_sample():
    """Generate one epipe training sample."""
    values = generate_epipe_values()
    template = random.choice(EPIPE_TEMPLATES)

    instruction = template.format(
        service_name=values["service-name"],
        customer_id=values["customer-id"],
        ne_service_id=values["ne-service-id"],
        mtu=values["mtu"],
        site_a_device=values["site-a.device-id"],
        site_a_port=values["site-a.endpoint[0].port-id"],
        site_b_device=values["site-b.device-id"],
        site_b_port=values["site-b.endpoint[0].port-id"],
        vlan=values["site-a.endpoint[0].outer-vlan-tag"],
        sdp_id_1=values["sdp[0].sdp-id"],
        sdp_id_2=values["sdp[1].sdp-id"],
    )

    output = {
        "intent_type": "epipe",
        "template_name": "ePIPE-Service-Using-SDP",
        "fill_values": values,
    }

    return instruction, output


def build_tunnel_sample():
    """Generate one tunnel training sample."""
    values = generate_tunnel_values()
    template = random.choice(TUNNEL_TEMPLATES)

    instruction = template.format(
        source_device=values["source-ne-id"],
        dest_device=values["destination-ne-id"],
        sdp_id=values["sdp-id"],
        tunnel_name=values["name"],
    )

    output = {
        "intent_type": "tunnel",
        "template_name": "MPLSTunnelsWithBGP",
        "fill_values": values,
    }

    return instruction, output


def build_vprn_sample(num_sites, interfaces_per_site):
    """Generate one VPRN training sample."""
    values = generate_vprn_values(num_sites=num_sites, interfaces_per_site=interfaces_per_site)
    project = values["service-name"].split("-")[-1]  # extract project name from service-name

    if num_sites == 1:
        template = random.choice(VPRN_TEMPLATES_1SITE)
        interfaces_desc = format_interfaces_desc(values, 0, interfaces_per_site)

        format_args = {
            "service_name": values["service-name"],
            "customer_id": values["customer-id"],
            "site0_device": values["site[0].device-id"],
            "site0_svc_id": values["site[0].ne-service-id"],
            "site0_rd": values["site[0].route-distinguisher"],
            "site0_vrf_import": values["site[0].vrf-import"][0],
            "site0_vrf_export": values["site[0].vrf-export"][0],
            "interfaces_desc": interfaces_desc,
            "project_name": project,
        }

        instruction = template.format(**format_args)

    else:  # 2 sites
        template = random.choice(VPRN_TEMPLATES_2SITE)
        site0_ifaces = format_interfaces_desc(values, 0, interfaces_per_site)
        site1_ifaces = format_interfaces_desc(values, 1, interfaces_per_site)

        format_args = {
            "service_name": values["service-name"],
            "customer_id": values["customer-id"],
            "site0_device": values["site[0].device-id"],
            "site0_svc_id": values["site[0].ne-service-id"],
            "site0_rd": values["site[0].route-distinguisher"],
            "site0_vrf_import": values["site[0].vrf-import"][0],
            "site0_vrf_export": values["site[0].vrf-export"][0],
            "site0_interfaces_desc": site0_ifaces,
            "site1_device": values["site[1].device-id"],
            "site1_svc_id": values["site[1].ne-service-id"],
            "site1_rd": values["site[1].route-distinguisher"],
            "site1_vrf_import": values["site[1].vrf-import"][0],
            "site1_vrf_export": values["site[1].vrf-export"][0],
            "site1_interfaces_desc": site1_ifaces,
            "project_name": project,
        }

        instruction = template.format(**format_args)

    # Convert list values to plain lists for JSON serialization
    output = {
        "intent_type": "vprn",
        "template_name": "VPRNServiceTemplate",
        "fill_values": values,
    }

    return instruction, output


def make_chat_sample(instruction, output):
    """Wrap instruction and output into chat message format."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": json.dumps(output, indent=2)},
        ]
    }


def generate_all_samples(
    n_epipe=600, n_tunnel=400, n_vprn_1site=300, n_vprn_2site=200,
    seed=42
):
    """Generate all training samples."""
    random.seed(seed)
    samples = []

    print(f"Generating {n_tunnel} tunnel samples...")
    for _ in range(n_tunnel):
        instruction, output = build_tunnel_sample()
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_epipe} epipe samples...")
    for _ in range(n_epipe):
        instruction, output = build_epipe_sample()
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_vprn_1site} VPRN (1-site) samples...")
    for _ in range(n_vprn_1site):
        n_ifaces = random.choice([1, 2, 2, 3, 3])
        instruction, output = build_vprn_sample(num_sites=1, interfaces_per_site=n_ifaces)
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_vprn_2site} VPRN (2-site) samples...")
    for _ in range(n_vprn_2site):
        n_ifaces = random.choice([1, 2, 2, 3])
        instruction, output = build_vprn_sample(num_sites=2, interfaces_per_site=n_ifaces)
        samples.append(make_chat_sample(instruction, output))

    return samples


def validate_and_split(samples, train_ratio=0.8, val_ratio=0.1, test_ratio=0.1):
    """Validate all samples and split into train/val/test."""
    valid_samples = []
    invalid_count = 0

    for s in samples:
        output_str = s["messages"][2]["content"]
        is_valid, errors = validate_sample({"output": output_str})
        if is_valid:
            valid_samples.append(s)
        else:
            invalid_count += 1
            if invalid_count <= 5:
                print(f"  Invalid sample: {errors}")

    print(f"\nValidation: {len(valid_samples)} valid, {invalid_count} invalid")

    random.shuffle(valid_samples)

    n = len(valid_samples)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)

    train = valid_samples[:n_train]
    val = valid_samples[n_train:n_train + n_val]
    test = valid_samples[n_train + n_val:]

    return train, val, test


def write_jsonl(samples, filepath):
    """Write samples to a JSONL file."""
    with open(filepath, "w") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"Wrote {len(samples)} samples to {filepath}")


def build_golden_tests():
    """Build golden test cases from real Sarvesh operational data."""
    golden = []

    # Golden test 1: Real tunnel from SarveshIntent.txt
    golden.append(make_chat_sample(
        "Create an MPLS tunnel from 192.168.0.16 to 192.168.0.37 with SDP ID 1637. "
        "Name it 'SDP-from-C2U16-to-C2U37'. Use BGP signaling with TLDP.",
        {
            "intent_type": "tunnel",
            "template_name": "MPLSTunnelsWithBGP",
            "fill_values": {
                "source-ne-id": "192.168.0.16",
                "sdp-id": "1637",
                "destination-ne-id": "192.168.0.37",
                "name": "SDP-from-C2U16-to-C2U37",
            }
        }
    ))

    # Golden test 2: Real epipe from SarveshIntent.txt
    golden.append(make_chat_sample(
        "Create an E-Pipe service named 'Epipe-VLAN-1001-nvlink-C2U16-to-a5000dual-C2U35' "
        "for customer 10 (NE service ID 2001). Connect device 192.168.0.37 on port 1/2/c4/1 "
        "to device 192.168.0.16 on port 1/2/c5/1 using VLAN 1001. MTU is 1492. "
        "Use SDP 3716 and 1637.",
        {
            "intent_type": "epipe",
            "template_name": "ePIPE-Service-Using-SDP",
            "fill_values": {
                "service-name": "Epipe-VLAN-1001-nvlink-C2U16-to-a5000dual-C2U35",
                "customer-id": 10,
                "ne-service-id": 2001,
                "mtu": 1492,
                "site-a.device-id": "192.168.0.37",
                "site-a.endpoint[0].port-id": "1/2/c4/1",
                "site-a.endpoint[0].outer-vlan-tag": 1001,
                "site-b.device-id": "192.168.0.16",
                "site-b.endpoint[0].port-id": "1/2/c5/1",
                "site-b.endpoint[0].outer-vlan-tag": 1001,
                "sdp[0].sdp-id": "3716",
                "sdp[0].source-device-id": "192.168.0.37",
                "sdp[0].destination-device-id": "192.168.0.16",
                "sdp[1].sdp-id": "1637",
                "sdp[1].source-device-id": "192.168.0.16",
                "sdp[1].destination-device-id": "192.168.0.37",
            }
        }
    ))

    # Golden test 3: Tunnel in conversational style
    golden.append(make_chat_sample(
        "I need an SDP tunnel between routers 192.168.0.16 and 192.168.0.37. "
        "Use BGP signaling with SDP ID 1637. Name it 'SDP-from-C2U16-to-C2U37'.",
        {
            "intent_type": "tunnel",
            "template_name": "MPLSTunnelsWithBGP",
            "fill_values": {
                "source-ne-id": "192.168.0.16",
                "sdp-id": "1637",
                "destination-ne-id": "192.168.0.37",
                "name": "SDP-from-C2U16-to-C2U37",
            }
        }
    ))

    # Golden test 4: Epipe in terse style
    golden.append(make_chat_sample(
        "Deploy epipe: Epipe-VLAN-1001-nvlink-C2U16-to-a5000dual-C2U35, cust=10, svc-id=2001, mtu=1492, "
        "192.168.0.37:1/2/c4/1 <-> 192.168.0.16:1/2/c5/1, VLAN 1001, SDP 3716/1637",
        {
            "intent_type": "epipe",
            "template_name": "ePIPE-Service-Using-SDP",
            "fill_values": {
                "service-name": "Epipe-VLAN-1001-nvlink-C2U16-to-a5000dual-C2U35",
                "customer-id": 10,
                "ne-service-id": 2001,
                "mtu": 1492,
                "site-a.device-id": "192.168.0.37",
                "site-a.endpoint[0].port-id": "1/2/c4/1",
                "site-a.endpoint[0].outer-vlan-tag": 1001,
                "site-b.device-id": "192.168.0.16",
                "site-b.endpoint[0].port-id": "1/2/c5/1",
                "site-b.endpoint[0].outer-vlan-tag": 1001,
                "sdp[0].sdp-id": "3716",
                "sdp[0].source-device-id": "192.168.0.37",
                "sdp[0].destination-device-id": "192.168.0.16",
                "sdp[1].sdp-id": "1637",
                "sdp[1].source-device-id": "192.168.0.16",
                "sdp[1].destination-device-id": "192.168.0.37",
            }
        }
    ))

    # Golden test 5: VPRN single site based on Sarvesh's real VPRN (site 1: Delta cluster)
    golden.append(make_chat_sample(
        "Create a VPRN L3 VPN service named 'VPRN-1001-OurAI' for customer 20. "
        "Configure site on device 192.168.0.16 with service ID 1001. "
        "Route distinguisher: 65008:1001. VRF policies: import OurAI-VRF-Import, export OurAI-VRF-Export. "
        "Interfaces: Delta-Cluster-NAS1 on port 1/2/c4/1 with IP 100.71.108.201/31; "
        "Delta-Cluster-Master on port lag-AFOR8-4x10GE with IP 100.71.108.197/31; "
        "Delta-Cluster-Worker-1 on port lag-AFOR3-4x10GE with IP 100.71.108.195/31.",
        {
            "intent_type": "vprn",
            "template_name": "VPRNServiceTemplate",
            "fill_values": {
                "service-name": "VPRN-1001-OurAI",
                "customer-id": 20,
                "site[0].site-name": "VPRN-1001-OurAI",
                "site[0].device-id": "192.168.0.16",
                "site[0].ne-service-id": 1001,
                "site[0].route-distinguisher": "65008:1001",
                "site[0].vrf-import": ["OurAI-VRF-Import"],
                "site[0].vrf-export": ["OurAI-VRF-Export"],
                "site[0].interface[0].interface-name": "Delta-Cluster-NAS1",
                "site[0].interface[0].sap.port-id": "1/2/c4/1",
                "site[0].interface[0].ipv4.primary.address": "100.71.108.201",
                "site[0].interface[0].ipv4.primary.prefix-length": 31,
                "site[0].interface[1].interface-name": "Delta-Cluster-Master",
                "site[0].interface[1].sap.port-id": "lag-AFOR8-4x10GE",
                "site[0].interface[1].ipv4.primary.address": "100.71.108.197",
                "site[0].interface[1].ipv4.primary.prefix-length": 31,
                "site[0].interface[2].interface-name": "Delta-Cluster-Worker-1",
                "site[0].interface[2].sap.port-id": "lag-AFOR3-4x10GE",
                "site[0].interface[2].ipv4.primary.address": "100.71.108.195",
                "site[0].interface[2].ipv4.primary.prefix-length": 31,
            }
        }
    ))

    return golden


if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(__file__), "generated")
    os.makedirs(output_dir, exist_ok=True)

    print("=== Generating NSP Intent Training Data ===\n")
    samples = generate_all_samples(
        n_epipe=600, n_tunnel=400, n_vprn_1site=300, n_vprn_2site=200, seed=42
    )
    print(f"\nTotal samples generated: {len(samples)}")

    print("\n--- Validating and splitting ---")
    train, val, test = validate_and_split(samples)

    print(f"\nSplit: train={len(train)}, val={len(val)}, test={len(test)}")

    write_jsonl(train, os.path.join(output_dir, "train.jsonl"))
    write_jsonl(val, os.path.join(output_dir, "val.jsonl"))
    write_jsonl(test, os.path.join(output_dir, "test.jsonl"))

    print("\n--- Building golden test cases ---")
    golden = build_golden_tests()
    write_jsonl(golden, os.path.join(output_dir, "golden_tests.jsonl"))

    # Print a sample for verification
    print("\n=== Sample Training Example ===")
    sample = train[0]
    print(f"USER: {sample['messages'][1]['content'][:200]}...")
    print(f"ASSISTANT: {sample['messages'][2]['content'][:200]}...")
    print("\n=== Done ===")
