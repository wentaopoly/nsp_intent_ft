"""
Per-intent fill_values generators for training data synthesis (Milestone 3).

This module is a slim orchestration layer over `value_generators.py`. It is
NO LONGER the source of field-type / range / enum knowledge — that lives in
the YANG schemas under `data/yang/<intent>/` and is enforced by the validator.

What this module owns:
  - The "core field selection" per intent type — i.e. which YANG leaves the
    training data should populate, and how many list entries to create. The
    selection is intentionally narrow because the existing fine-tuned model
    was trained on ~15 fields per sample and we want comparable distributions.
  - The cross-field semantic constraints (e.g. epipe SDP[0] source = site-a
    device, vprn sites have distinct device-ids) that YANG itself cannot
    express.

What this module does NOT own (any more):
  - The dictionaries of {field_path: type/range/required} — those were
    deleted; YANG provides them.
  - The low-level random_* helpers and the project-name / cluster-name
    vocabulary — moved to `value_generators.py` (Phase B).

Public API:
  generate_intent_values(intent_type, **opts) -> dict[str, Any]
      Single dispatcher used by `generate_training_data.py` and tests.
      Returns a flat fill_values dict ready to be merged via
      `inference.merge_fill_values.merge_fill_values`.

  generate_{epipe,tunnel,vprn,vpls,ies,etree,cpipe,evpn_epipe,evpn_vpls}_values
      Per-type entry points kept as thin wrappers. The original 3 wrappers
      preserve their pre-M3 signatures so the existing data-generation script
      keeps working unchanged.
"""

from __future__ import annotations

import random
from typing import Any, Dict

from value_generators import (
    # vocab pools
    CLUSTER_NAMES, CLUSTER_ROLES, PROJECT_NAMES, SITE_DESCRIPTIONS,
    # primitive generators
    random_device_ip, random_interface_ip, random_port_id, random_vlan,
    random_inner_vlan_tag, random_customer_id, random_service_id,
    random_mtu, random_route_distinguisher_with_id, random_route_target,
    random_project_name, random_cluster_name, random_interface_name,
    random_tunnel_name, derive_sdp_id, random_evi,
    # service-name generators per intent type
    random_service_name_epipe, random_service_name_vprn,
    random_service_name_vpls, random_service_name_ies,
    random_service_name_etree, random_service_name_cpipe,
    random_service_name_evpn_epipe, random_service_name_evpn_vpls,
)


# ---------------------------------------------------------------------------
# Helpers shared across generators
# ---------------------------------------------------------------------------


def _two_distinct_device_ips() -> tuple[str, str]:
    a = random_device_ip()
    b = random_device_ip()
    while b == a:
        b = random_device_ip()
    return a, b


def _n_distinct_device_ips(n: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        ip = random_device_ip()
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def _interface_block(prefix: str, cluster: str, role_idx: int,
                     used_iface_ips: set[str]) -> dict[str, Any]:
    """Build the 4 standard interface fields for a given list-index prefix."""
    role = CLUSTER_ROLES[role_idx % len(CLUSTER_ROLES)]
    iface_name = f"{cluster}-Cluster-{role}"
    iface_ip = random_interface_ip()
    while iface_ip in used_iface_ips:
        iface_ip = random_interface_ip()
    used_iface_ips.add(iface_ip)
    return {
        f"{prefix}.interface-name": iface_name,
        f"{prefix}.sap.port-id": random_port_id(),
        f"{prefix}.ipv4.primary.address": iface_ip,
        f"{prefix}.ipv4.primary.prefix-length": random.choice([24, 28, 30, 31]),
    }


# ---------------------------------------------------------------------------
# epipe (existing — preserves pre-M3 16-field signature)
# ---------------------------------------------------------------------------


def generate_epipe_values() -> Dict[str, Any]:
    """Generate a complete fill_values dict for an epipe intent."""
    site_a_ip, site_b_ip = _two_distinct_device_ips()
    vlan = random_vlan()
    site_a_desc = random.choice(SITE_DESCRIPTIONS)
    site_b_desc = random.choice(SITE_DESCRIPTIONS)
    sdp_id_1 = derive_sdp_id(site_a_ip, site_b_ip)
    sdp_id_2 = derive_sdp_id(site_b_ip, site_a_ip)

    return {
        "service-name": random_service_name_epipe(vlan, site_a_desc, site_b_desc),
        "customer-id": random_customer_id(),
        "ne-service-id": random_service_id(),
        "mtu": random_mtu(),
        "site-a.device-id": site_a_ip,
        "site-a.endpoint[0].port-id": random_port_id(),
        "site-a.endpoint[0].outer-vlan-tag": vlan,
        "site-b.device-id": site_b_ip,
        "site-b.endpoint[0].port-id": random_port_id(),
        "site-b.endpoint[0].outer-vlan-tag": vlan,
        "sdp[0].sdp-id": sdp_id_1,
        "sdp[0].source-device-id": site_a_ip,
        "sdp[0].destination-device-id": site_b_ip,
        "sdp[1].sdp-id": sdp_id_2,
        "sdp[1].source-device-id": site_b_ip,
        "sdp[1].destination-device-id": site_a_ip,
    }


# ---------------------------------------------------------------------------
# tunnel (existing — preserves pre-M3 4-field signature)
# ---------------------------------------------------------------------------


def generate_tunnel_values() -> Dict[str, Any]:
    """Generate a complete fill_values dict for a tunnel intent."""
    src_ip, dst_ip = _two_distinct_device_ips()
    return {
        "source-ne-id": src_ip,
        "sdp-id": derive_sdp_id(src_ip, dst_ip),
        "destination-ne-id": dst_ip,
        "name": random_tunnel_name(src_ip, dst_ip),
    }


# ---------------------------------------------------------------------------
# vprn (existing — preserves pre-M3 multi-site signature)
# ---------------------------------------------------------------------------


def generate_vprn_values(num_sites: int = 1, interfaces_per_site: int = 2) -> Dict[str, Any]:
    """Generate a complete fill_values dict for a VPRN intent."""
    project = random_project_name()
    service_id = random_service_id()

    values: Dict[str, Any] = {
        "service-name": random_service_name_vprn(service_id, project),
        "customer-id": random_customer_id(),
    }

    site_ips = _n_distinct_device_ips(num_sites)
    for s, device_ip in enumerate(site_ips):
        rd = random_route_distinguisher_with_id(service_id)
        values[f"site[{s}].site-name"] = random_service_name_vprn(service_id, project)
        values[f"site[{s}].device-id"] = device_ip
        values[f"site[{s}].ne-service-id"] = service_id
        values[f"site[{s}].route-distinguisher"] = rd
        values[f"site[{s}].vrf-import"] = [f"{project}-VRF-Import"]
        values[f"site[{s}].vrf-export"] = [f"{project}-VRF-Export"]

        cluster = random_cluster_name()
        used_iface_ips: set[str] = set()
        for i in range(interfaces_per_site):
            values.update(_interface_block(
                f"site[{s}].interface[{i}]", cluster, i, used_iface_ips
            ))

    return values


# ---------------------------------------------------------------------------
# vpls (NEW M3) — VPLS multi-site L2 broadcast domain
# ---------------------------------------------------------------------------


def generate_vpls_values(num_sites: int = 2) -> Dict[str, Any]:
    """Generate a complete fill_values dict for a VPLS intent.

    VPLS provides a multi-point Ethernet bridging domain across multiple
    sites. Each site has its own SAP into the VPLS, and the sites form a
    full mesh of SDP bindings between every pair.

    YANG paths used (after wrapper-stripping):
      - site[N].device-id      (list key)
      - site[N].sap[0].port-id, inner-vlan-tag, outer-vlan-tag  (3-tuple list key)
      - sdp[K].source-device-id, sdp-id  (2-tuple list key)
    """
    project = random_project_name()
    service_id = random_service_id()
    vlan = random_vlan()

    values: Dict[str, Any] = {
        "service-name": random_service_name_vpls(service_id, project),
        "customer-id": random_customer_id(),
        "ne-service-id": service_id,
        "mtu": random_mtu(),
    }

    site_ips = _n_distinct_device_ips(num_sites)
    for s, device_ip in enumerate(site_ips):
        prefix = f"site[{s}]"
        values[f"{prefix}.device-id"] = device_ip
        values[f"{prefix}.sap[0].port-id"] = random_port_id()
        values[f"{prefix}.sap[0].inner-vlan-tag"] = -1
        values[f"{prefix}.sap[0].outer-vlan-tag"] = vlan

    # Full mesh of SDPs: one per ordered pair of distinct sites
    sdp_idx = 0
    for i, src_ip in enumerate(site_ips):
        for j, dst_ip in enumerate(site_ips):
            if i == j:
                continue
            values[f"sdp[{sdp_idx}].sdp-id"] = derive_sdp_id(src_ip, dst_ip)
            values[f"sdp[{sdp_idx}].source-device-id"] = src_ip
            values[f"sdp[{sdp_idx}].destination-device-id"] = dst_ip
            sdp_idx += 1

    return values


# ---------------------------------------------------------------------------
# ies (NEW M3) — Internet Enhanced Service (single-site routed access)
# ---------------------------------------------------------------------------


def generate_ies_values(interfaces_per_site: int = 2) -> Dict[str, Any]:
    """Generate a complete fill_values dict for an IES intent.

    IES is a single-site Internet Enhanced Service: a routed access service
    where the PE router exposes one or more L3 interfaces directly to the
    customer (no VRF involved). Always one site, multiple interfaces.
    """
    project = random_project_name()
    service_id = random_service_id()

    values: Dict[str, Any] = {
        "service-name": random_service_name_ies(service_id, project),
        "customer-id": random_customer_id(),
        "ne-service-id": service_id,
        "site[0].device-id": random_device_ip(),
        "site[0].site-name": random_service_name_ies(service_id, project),
    }

    cluster = random_cluster_name()
    used_iface_ips: set[str] = set()
    for i in range(interfaces_per_site):
        values.update(_interface_block(
            f"site[0].interface[{i}]", cluster, i, used_iface_ips
        ))

    return values


# ---------------------------------------------------------------------------
# etree (NEW M3) — E-Tree (root/leaf VPLS variant)
# ---------------------------------------------------------------------------


def generate_etree_values(num_root_sites: int = 1, num_leaf_sites: int = 2) -> Dict[str, Any]:
    """Generate a complete fill_values dict for an E-Tree intent.

    E-Tree is a VPLS variant where SAPs are categorized as either ROOT
    (can talk to everyone) or LEAF (can only talk to roots, not other
    leaves). Standard topology: ≥1 root site + ≥2 leaf sites.

    Root vs leaf is encoded by the boolean YANG leaf `etree-leaf` on each
    SAP entry: True means leaf-SAP, False/missing means root-SAP.
    """
    project = random_project_name()
    service_id = random_service_id()
    vlan = random_vlan()

    values: Dict[str, Any] = {
        "service-name": random_service_name_etree(service_id, project),
        "customer-id": random_customer_id(),
        "ne-service-id": service_id,
        "mtu": random_mtu(),
    }

    total = num_root_sites + num_leaf_sites
    site_ips = _n_distinct_device_ips(total)
    for s, device_ip in enumerate(site_ips):
        is_leaf = s >= num_root_sites
        prefix = f"site[{s}]"
        values[f"{prefix}.device-id"] = device_ip
        values[f"{prefix}.sap[0].port-id"] = random_port_id()
        values[f"{prefix}.sap[0].inner-vlan-tag"] = -1
        values[f"{prefix}.sap[0].outer-vlan-tag"] = vlan
        values[f"{prefix}.sap[0].etree-leaf"] = is_leaf

    # SDP mesh — etree filtering happens at SAP level via etree-leaf
    sdp_idx = 0
    for i, src_ip in enumerate(site_ips):
        for j, dst_ip in enumerate(site_ips):
            if i == j:
                continue
            values[f"sdp[{sdp_idx}].sdp-id"] = derive_sdp_id(src_ip, dst_ip)
            values[f"sdp[{sdp_idx}].source-device-id"] = src_ip
            values[f"sdp[{sdp_idx}].destination-device-id"] = dst_ip
            sdp_idx += 1

    return values


# ---------------------------------------------------------------------------
# cpipe (NEW M3) — Circuit Pipe (TDM circuit emulation)
# ---------------------------------------------------------------------------


def generate_cpipe_values() -> Dict[str, Any]:
    """Generate a complete fill_values dict for a Cpipe intent.

    Cpipe is a TDM (E1/T1/SONET/SDH) circuit emulation service. The two
    endpoints pseudo-wire a TDM bitstream over MPLS.

    YANG paths:
      - cpipe.vc-type:    enum [satope1, satopt1, satope3, satopt3, cesopsn]
      - cpipe.site-a/b.endpoint[*]: list keyed by [port-id, time-slots]
        time-slots is a free-form string like "1-32" (E1 channels) or
        "1-24" (T1 channels). Both endpoints must use the same value.
    """
    site_a_ip, site_b_ip = _two_distinct_device_ips()
    project = random_project_name()
    service_id = random_service_id()
    vc_type = random.choice(["cesopsn", "satope1", "satopt1", "satope3", "satopt3"])
    time_slots = random.choice(["1-32", "1-24", "1-31", "2-32", "1-15"])

    return {
        "service-name": random_service_name_cpipe(service_id, project),
        "customer-id": random_customer_id(),
        "ne-service-id": service_id,
        "vc-type": vc_type,
        "site-a.device-id": site_a_ip,
        "site-a.endpoint[0].port-id": random_port_id(),
        "site-a.endpoint[0].time-slots": time_slots,
        "site-b.device-id": site_b_ip,
        "site-b.endpoint[0].port-id": random_port_id(),
        "site-b.endpoint[0].time-slots": time_slots,
        "sdp[0].sdp-id": derive_sdp_id(site_a_ip, site_b_ip),
        "sdp[0].source-device-id": site_a_ip,
        "sdp[0].destination-device-id": site_b_ip,
        "sdp[1].sdp-id": derive_sdp_id(site_b_ip, site_a_ip),
        "sdp[1].source-device-id": site_b_ip,
        "sdp[1].destination-device-id": site_a_ip,
    }


# ---------------------------------------------------------------------------
# evpn-epipe (NEW M3) — EVPN-based point-to-point Ethernet
# ---------------------------------------------------------------------------


def generate_evpn_epipe_values() -> Dict[str, Any]:
    """Generate a complete fill_values dict for an EVPN-Epipe intent.

    EVPN-Epipe is an E-Line service signalled via BGP-EVPN instead of
    classic LDP. Each side has an EVI number (EVPN Instance) per site
    that ties the two endpoints together.

    YANG paths:
      - evpn-epipe.site-a/b.device-id, evi, site-name
      - evpn-epipe.site-a/b.sap-details.sap[*]: list keyed by
        [port-id, inner-vlan-tag, outer-vlan-tag] -> after wrapper
        stripping the user path is `site-a.sap[0].port-id` etc.
    """
    site_a_ip, site_b_ip = _two_distinct_device_ips()
    vlan = random_vlan()
    project = random_project_name()
    service_id = random_service_id()
    evi = random_evi()

    return {
        "service-name": random_service_name_evpn_epipe(service_id, project),
        "customer-id": random_customer_id(),
        "ne-service-id": service_id,
        "site-a.device-id": site_a_ip,
        "site-a.evi": evi,
        "site-a.sap[0].port-id": random_port_id(),
        "site-a.sap[0].inner-vlan-tag": -1,
        "site-a.sap[0].outer-vlan-tag": vlan,
        "site-b.device-id": site_b_ip,
        "site-b.evi": evi,
        "site-b.sap[0].port-id": random_port_id(),
        "site-b.sap[0].inner-vlan-tag": -1,
        "site-b.sap[0].outer-vlan-tag": vlan,
    }


# ---------------------------------------------------------------------------
# evpn-vpls (NEW M3) — EVPN-based multipoint Ethernet
# ---------------------------------------------------------------------------


def generate_evpn_vpls_values(num_sites: int = 2) -> Dict[str, Any]:
    """Generate a complete fill_values dict for an EVPN-VPLS intent.

    EVPN-VPLS is the BGP-EVPN-signalled multi-point Ethernet bridging
    domain. Each site participates in the same EVI; MAC learning is via
    BGP advertisements rather than data-plane flooding.

    YANG paths:
      - evpn-vpls.site-details.site[*]: list keyed by [device-id]
      - evpn-vpls.site-details.site[*].sap-details.sap[*]: keyed by
        [port-id, inner-vlan-tag, outer-vlan-tag]
    """
    project = random_project_name()
    service_id = random_service_id()
    vlan = random_vlan()

    values: Dict[str, Any] = {
        "service-name": random_service_name_evpn_vpls(service_id, project),
        "customer-id": random_customer_id(),
        "ne-service-id": service_id,
        "mtu": random_mtu(),
    }

    site_ips = _n_distinct_device_ips(num_sites)
    for s, device_ip in enumerate(site_ips):
        prefix = f"site[{s}]"
        values[f"{prefix}.device-id"] = device_ip
        values[f"{prefix}.sap[0].port-id"] = random_port_id()
        values[f"{prefix}.sap[0].inner-vlan-tag"] = -1
        values[f"{prefix}.sap[0].outer-vlan-tag"] = vlan

    return values


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


_GENERATORS = {
    "epipe":      generate_epipe_values,
    "tunnel":     generate_tunnel_values,
    "vprn":       generate_vprn_values,
    "vpls":       generate_vpls_values,
    "ies":        generate_ies_values,
    "etree":      generate_etree_values,
    "cpipe":      generate_cpipe_values,
    "evpn-epipe": generate_evpn_epipe_values,
    "evpn-vpls":  generate_evpn_vpls_values,
}


def generate_intent_values(intent_type: str, **opts) -> Dict[str, Any]:
    """Single dispatcher for generating fill_values across all 9 intent types."""
    fn = _GENERATORS.get(intent_type)
    if fn is None:
        raise ValueError(f"Unknown intent_type: {intent_type!r}")
    return fn(**opts)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, ".")
    from intent_validator import validate_full
    sys.path.insert(0, "../inference")
    from merge_fill_values import merge_fill_values

    print("=== Per-intent generation + 4-tier validation ===\n")
    for it in ("epipe", "tunnel", "vprn", "vpls", "ies", "etree", "cpipe", "evpn-epipe", "evpn-vpls"):
        # Use defaults; vprn / etree / vpls / evpn-vpls all support multi-site
        if it == "vprn":
            fv = generate_intent_values(it, num_sites=2, interfaces_per_site=2)
        else:
            fv = generate_intent_values(it)

        try:
            merged = merge_fill_values(it, fv)
            ok, errs = validate_full(it, fv, merged)
        except Exception as e:
            ok, errs = False, {"crash": [str(e)]}

        n_fields = len(fv)
        status = "✓" if ok else "✗"
        print(f"  {status} {it:<12} ({n_fields} fields)  ok={ok}")
        if not ok:
            for tier, e_list in errs.items():
                if e_list:
                    print(f"      {tier}: {e_list[:3]}")
