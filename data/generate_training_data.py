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
    generate_vpls_values, generate_ies_values, generate_etree_values,
    generate_cpipe_values, generate_evpn_epipe_values, generate_evpn_vpls_values,
    _roll_evpn_epipe_args, _roll_evpn_vpls_args,
)
from value_generators import random_project_name
from instruction_templates import (
    EPIPE_TEMPLATES, TUNNEL_TEMPLATES,
    VPRN_TEMPLATES_1SITE, VPRN_TEMPLATES_2SITE,
    VPLS_TEMPLATES_2SITE, IES_TEMPLATES, ETREE_TEMPLATES,
    CPIPE_TEMPLATES, EVPN_EPIPE_TEMPLATES, EVPN_VPLS_TEMPLATES_2SITE,
    format_interfaces_desc, format_ies_interfaces_desc, format_etree_leaves_desc,
)
from validate_sample import validate_sample

SYSTEM_PROMPT = (
    "You are an NSP (Network Services Platform) intent configuration assistant. "
    "Convert each natural language network service request into a single JSON object with three fields:\n"
    "- intent_type: one of \"epipe\", \"tunnel\", \"vprn\", \"vpls\", \"ies\", \"etree\", "
    "\"cpipe\", \"evpn-epipe\", \"evpn-vpls\"\n"
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


def build_vpls_sample(num_sites=2):
    """Generate one VPLS training sample."""
    values = generate_vpls_values(num_sites=num_sites)
    template = random.choice(VPLS_TEMPLATES_2SITE)

    args = {
        "service_name":  values["service-name"],
        "customer_id":   values["customer-id"],
        "ne_service_id": values["ne-service-id"],
        "mtu":           values["mtu"],
        "site0_device":  values["site[0].device-id"],
        "site0_port":    values["site[0].sap[0].port-id"],
        "site1_device":  values["site[1].device-id"],
        "site1_port":    values["site[1].sap[0].port-id"],
        "vlan":          values["site[0].sap[0].outer-vlan-tag"],
    }
    instruction = template.format(**args)
    output = {
        "intent_type": "vpls",
        "template_name": "VPLSServiceTemplate",
        "fill_values": values,
    }
    return instruction, output


def build_ies_sample(interfaces_per_site=2):
    """Generate one IES training sample."""
    values = generate_ies_values(interfaces_per_site=interfaces_per_site)
    template = random.choice(IES_TEMPLATES)

    args = {
        "service_name":   values["service-name"],
        "customer_id":    values["customer-id"],
        "ne_service_id":  values["ne-service-id"],
        "site_device":    values["site[0].device-id"],
        "interfaces_desc": format_ies_interfaces_desc(values, interfaces_per_site),
        "project_name":   random_project_name(),
    }
    instruction = template.format(**args)
    output = {
        "intent_type": "ies",
        "template_name": "IESServiceTemplate",
        "fill_values": values,
    }
    return instruction, output


def build_etree_sample(num_leaf_sites=2):
    """Generate one E-Tree training sample (1 root + N leaves)."""
    values = generate_etree_values(num_leaf_sites=num_leaf_sites)
    template = random.choice(ETREE_TEMPLATES)

    args = {
        "service_name":  values["service-name"],
        "customer_id":   values["customer-id"],
        "ne_service_id": values["ne-service-id"],
        "mtu":           values["mtu"],
        "vlan":          values["site[0].sap[0].outer-vlan-tag"],
        "root0_device":  values["site[0].device-id"],
        "root0_port":    values["site[0].sap[0].port-id"],
        "leaves_desc":   format_etree_leaves_desc(values, 1, num_leaf_sites),
    }
    instruction = template.format(**args)
    output = {
        "intent_type": "etree",
        "template_name": "ETreeServiceTemplate",
        "fill_values": values,
    }
    return instruction, output


def build_cpipe_sample():
    """Generate one Cpipe training sample."""
    values = generate_cpipe_values()
    template = random.choice(CPIPE_TEMPLATES)

    args = {
        "service_name":  values["service-name"],
        "customer_id":   values["customer-id"],
        "ne_service_id": values["ne-service-id"],
        "vc_type":       values["vc-type"],
        "site_a_device": values["site-a.device-id"],
        "site_a_port":   values["site-a.endpoint[0].port-id"],
        "site_b_device": values["site-b.device-id"],
        "site_b_port":   values["site-b.endpoint[0].port-id"],
        "time_slots":    values["site-a.endpoint[0].time-slots"],
    }
    instruction = template.format(**args)
    output = {
        "intent_type": "cpipe",
        "template_name": "CpipeTDMService",
        "fill_values": values,
    }
    return instruction, output


def build_evpn_epipe_sample():
    """Generate one EVPN-Epipe training sample.

    M3.5-fix: now uses the pure-function generator. We roll instruction-arg
    values once, then pass them to BOTH the generator (which converts them
    into fill_values via deterministic rules) AND the instruction template
    formatter. This guarantees every value the model has to predict is
    derivable from the instruction it sees.
    """
    args = _roll_evpn_epipe_args()
    values = generate_evpn_epipe_values(**args)
    template = random.choice(EVPN_EPIPE_TEMPLATES)
    instruction = template.format(**args)
    output = {
        "intent_type": "evpn-epipe",
        "template_name": "EVPNEpipeService",
        "fill_values": values,
    }
    return instruction, output


def build_evpn_vpls_sample(num_sites=2):
    """Generate one EVPN-VPLS training sample.

    M3.5-fix: pure-function generator + arg-rolling helper, same pattern
    as evpn-epipe. The instruction template only uses site0/site1, so
    num_sites=2 is the supported case; the rolling helper handles higher
    counts but the template would need a matching format placeholder set.
    """
    args = _roll_evpn_vpls_args(num_sites=num_sites)
    values = generate_evpn_vpls_values(**args)
    template = random.choice(EVPN_VPLS_TEMPLATES_2SITE)
    instruction = template.format(
        service_name=args["service_name"],
        customer_id=args["customer_id"],
        ne_service_id=args["ne_service_id"],
        mtu=args["mtu"],
        evi=args["evi"],
        evpn_type=args["evpn_type"],
        vlan=args["vlan"],
        site0_device=args["site_devices"][0],
        site0_port=args["site_ports"][0],
        site1_device=args["site_devices"][1],
        site1_port=args["site_ports"][1],
    )
    output = {
        "intent_type": "evpn-vpls",
        "template_name": "EVPNVPLSService",
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
    n_vpls=400, n_ies=300, n_etree=300, n_cpipe=200,
    n_evpn_epipe=300, n_evpn_vpls=300,
    seed=42,
):
    """Generate all training samples across the 9 intent types."""
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

    print(f"Generating {n_vpls} VPLS samples...")
    for _ in range(n_vpls):
        instruction, output = build_vpls_sample(num_sites=2)
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_ies} IES samples...")
    for _ in range(n_ies):
        n_ifaces = random.choice([1, 2, 2, 3])
        instruction, output = build_ies_sample(interfaces_per_site=n_ifaces)
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_etree} E-Tree samples...")
    for _ in range(n_etree):
        n_leaf = random.choice([2, 2, 3])  # 1 root + 2-3 leaves
        instruction, output = build_etree_sample(num_leaf_sites=n_leaf)
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_cpipe} Cpipe samples...")
    for _ in range(n_cpipe):
        instruction, output = build_cpipe_sample()
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_evpn_epipe} EVPN-Epipe samples...")
    for _ in range(n_evpn_epipe):
        instruction, output = build_evpn_epipe_sample()
        samples.append(make_chat_sample(instruction, output))

    print(f"Generating {n_evpn_vpls} EVPN-VPLS samples...")
    for _ in range(n_evpn_vpls):
        instruction, output = build_evpn_vpls_sample(num_sites=2)
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

    # ----- M3 NEW intent type golden tests -----
    # Each new type gets 1-2 hand-curated samples to act as a regression
    # baseline for the retrained model. The values follow the same naming
    # conventions Sarvesh uses for the existing 3 types so that the goldens
    # are consistent across the corpus.

    # Golden 6: VPLS 2-site
    golden.append(make_chat_sample(
        "Create a VPLS service named 'VPLS-3001-OurAI' for customer 30 with NE service ID 3001 "
        "and MTU 1500. Site 1 is on device 192.168.0.16 using port 1/2/c4/1 with VLAN 100. "
        "Site 2 is on device 192.168.0.37 using port 1/2/c5/1 with VLAN 100.",
        {
            "intent_type": "vpls",
            "template_name": "VPLSServiceTemplate",
            "fill_values": {
                "service-name": "VPLS-3001-OurAI",
                "customer-id": 30,
                "ne-service-id": 3001,
                "mtu": 1500,
                "site[0].device-id": "192.168.0.16",
                "site[0].sap[0].port-id": "1/2/c4/1",
                "site[0].sap[0].inner-vlan-tag": -1,
                "site[0].sap[0].outer-vlan-tag": 100,
                "site[1].device-id": "192.168.0.37",
                "site[1].sap[0].port-id": "1/2/c5/1",
                "site[1].sap[0].inner-vlan-tag": -1,
                "site[1].sap[0].outer-vlan-tag": 100,
                "sdp[0].sdp-id": "1637",
                "sdp[0].source-device-id": "192.168.0.16",
                "sdp[0].destination-device-id": "192.168.0.37",
                "sdp[1].sdp-id": "3716",
                "sdp[1].source-device-id": "192.168.0.37",
                "sdp[1].destination-device-id": "192.168.0.16",
            },
        },
    ))

    # Golden 7: IES single site
    golden.append(make_chat_sample(
        "Create an IES (Internet Enhanced Service) named 'IES-4001-OurAI' for customer 40. "
        "NE service ID 4001. Provision the service on device 192.168.0.16. "
        "Configure these interfaces: Delta-Cluster-Master on port 1/2/c4/1 with IP 100.71.108.197/31; "
        "Delta-Cluster-Worker-1 on port lag-AFOR3-4x10GE with IP 100.71.108.195/31.",
        {
            "intent_type": "ies",
            "template_name": "IESServiceTemplate",
            "fill_values": {
                "service-name": "IES-4001-OurAI",
                "customer-id": 40,
                "ne-service-id": 4001,
                "site[0].device-id": "192.168.0.16",
                "site[0].site-name": "IES-4001-OurAI",
                "site[0].interface[0].interface-name": "Delta-Cluster-Master",
                "site[0].interface[0].sap.port-id": "1/2/c4/1",
                "site[0].interface[0].ipv4.primary.address": "100.71.108.197",
                "site[0].interface[0].ipv4.primary.prefix-length": 31,
                "site[0].interface[1].interface-name": "Delta-Cluster-Worker-1",
                "site[0].interface[1].sap.port-id": "lag-AFOR3-4x10GE",
                "site[0].interface[1].ipv4.primary.address": "100.71.108.195",
                "site[0].interface[1].ipv4.primary.prefix-length": 31,
            },
        },
    ))

    # Golden 8: E-Tree (1 root, 2 leaves — root↔leaf SDPs only, no leaf↔leaf)
    golden.append(make_chat_sample(
        "Create an E-Tree service named 'ETree-5001-OurAI' for customer 50 with NE service ID 5001, "
        "MTU 1500. Root site: 192.168.0.16 on port 1/2/c4/1. "
        "Leaf sites: device 192.168.0.37 on port 1/2/c5/1; device 192.168.0.38 on port 1/2/c6/1. "
        "All SAPs use VLAN 200.",
        {
            "intent_type": "etree",
            "template_name": "ETreeServiceTemplate",
            "fill_values": {
                "service-name": "ETree-5001-OurAI",
                "customer-id": 50,
                "ne-service-id": 5001,
                "mtu": 1500,
                "site[0].device-id": "192.168.0.16",
                "site[0].sap[0].port-id": "1/2/c4/1",
                "site[0].sap[0].inner-vlan-tag": -1,
                "site[0].sap[0].outer-vlan-tag": 200,
                "site[0].sap[0].etree-leaf": False,
                "site[1].device-id": "192.168.0.37",
                "site[1].sap[0].port-id": "1/2/c5/1",
                "site[1].sap[0].inner-vlan-tag": -1,
                "site[1].sap[0].outer-vlan-tag": 200,
                "site[1].sap[0].etree-leaf": True,
                "site[2].device-id": "192.168.0.38",
                "site[2].sap[0].port-id": "1/2/c6/1",
                "site[2].sap[0].inner-vlan-tag": -1,
                "site[2].sap[0].outer-vlan-tag": 200,
                "site[2].sap[0].etree-leaf": True,
                "sdp[0].sdp-id": "1637",
                "sdp[0].source-device-id": "192.168.0.16",
                "sdp[0].destination-device-id": "192.168.0.37",
                "sdp[1].sdp-id": "3716",
                "sdp[1].source-device-id": "192.168.0.37",
                "sdp[1].destination-device-id": "192.168.0.16",
                "sdp[2].sdp-id": "1638",
                "sdp[2].source-device-id": "192.168.0.16",
                "sdp[2].destination-device-id": "192.168.0.38",
                "sdp[3].sdp-id": "3816",
                "sdp[3].source-device-id": "192.168.0.38",
                "sdp[3].destination-device-id": "192.168.0.16",
            },
        },
    ))

    # Golden 9: Cpipe TDM circuit
    golden.append(make_chat_sample(
        "Create a Cpipe TDM circuit emulation service 'Cpipe-6001-OurAI' for customer 60 "
        "with NE service ID 6001. Encapsulation type vc-type cesopsn. "
        "Site A: device 192.168.0.16, port 1/2/c4/1, time-slots 1-32. "
        "Site B: device 192.168.0.37, port 1/2/c5/1, time-slots 1-32.",
        {
            "intent_type": "cpipe",
            "template_name": "CpipeTDMService",
            "fill_values": {
                "service-name": "Cpipe-6001-OurAI",
                "customer-id": 60,
                "ne-service-id": 6001,
                "vc-type": "cesopsn",
                "site-a.device-id": "192.168.0.16",
                "site-a.endpoint[0].port-id": "1/2/c4/1",
                "site-a.endpoint[0].time-slots": "1-32",
                "site-b.device-id": "192.168.0.37",
                "site-b.endpoint[0].port-id": "1/2/c5/1",
                "site-b.endpoint[0].time-slots": "1-32",
                "sdp[0].sdp-id": "1637",
                "sdp[0].source-device-id": "192.168.0.16",
                "sdp[0].destination-device-id": "192.168.0.37",
                "sdp[1].sdp-id": "3716",
                "sdp[1].source-device-id": "192.168.0.37",
                "sdp[1].destination-device-id": "192.168.0.16",
            },
        },
    ))

    # Golden 10: EVPN-Epipe (M3.5-fix: pure-function generator output, MPLS variant)
    golden_evpn_epipe_args = {
        "service_name": "EVPN-Epipe-7001-OurAI",
        "customer_id": 70,
        "ne_service_id": 7001,
        "evi": 7001,
        "evpn_type": "mpls",
        "vlan": 300,
        "device": "192.168.0.16",
        "port": "1/2/c4/1",
        "local_ac": "AC-OurAI-local",
        "remote_ac": "AC-OurAI-remote",
    }
    golden.append(make_chat_sample(
        "Create an mpls-EVPN E-Line service 'EVPN-Epipe-7001-OurAI' for customer 70 "
        "with NE service ID 7001 and EVI 7001. "
        "Configure on device 192.168.0.16, port 1/2/c4/1, VLAN 300. "
        "Local attachment circuit 'AC-OurAI-local', remote AC 'AC-OurAI-remote'.",
        {
            "intent_type": "evpn-epipe",
            "template_name": "EVPNEpipeService",
            "fill_values": generate_evpn_epipe_values(**golden_evpn_epipe_args),
        },
    ))

    # Golden 11: EVPN-VPLS (M3.5-fix: pure-function generator output, "both" variant)
    golden_evpn_vpls_args = {
        "service_name": "EVPN-VPLS-8001-OurAI",
        "customer_id": 80,
        "ne_service_id": 8001,
        "mtu": 1500,
        "evi": 8001,
        "evpn_type": "both",
        "vlan": 400,
        "site_devices": ["192.168.0.16", "192.168.0.37"],
        "site_ports": ["1/2/c4/1", "1/2/c5/1"],
    }
    golden.append(make_chat_sample(
        "Create a both-EVPN VPLS service 'EVPN-VPLS-8001-OurAI' for customer 80 "
        "with NE service ID 8001, EVI 8001, MTU 1500. "
        "Site 1: 192.168.0.16 on port 1/2/c4/1 with VLAN 400. "
        "Site 2: 192.168.0.37 on port 1/2/c5/1 with VLAN 400.",
        {
            "intent_type": "evpn-vpls",
            "template_name": "EVPNVPLSService",
            "fill_values": generate_evpn_vpls_values(**golden_evpn_vpls_args),
        },
    ))

    return golden


if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(__file__), "generated")
    os.makedirs(output_dir, exist_ok=True)

    print("=== Generating NSP Intent Training Data ===\n")
    samples = generate_all_samples(
        n_epipe=600, n_tunnel=400, n_vprn_1site=300, n_vprn_2site=200,
        n_vpls=400, n_ies=300, n_etree=300, n_cpipe=200,
        n_evpn_epipe=300, n_evpn_vpls=300,
        seed=42,
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
