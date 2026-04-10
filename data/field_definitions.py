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


def generate_etree_values(num_leaf_sites: int = 2) -> Dict[str, Any]:
    """Generate a complete fill_values dict for an E-Tree intent.

    E-Tree is a rooted multipoint VPLS variant (hub-and-spoke): one ROOT
    site can communicate with all leaves, but LEAF sites cannot talk to
    each other — only to the root. This is the standard E-Tree topology
    used in real deployments (1 hub + N spokes).

    M3.5-fix: two changes from the earlier version that scored 79% val_acc:

    1. **Root↔leaf SDPs only.** The previous full-mesh SDP generation
       (copied from vpls) created leaf↔leaf SDPs that violate E-Tree
       semantics — leaves can't communicate, so those SDPs should not
       exist. Removing them cuts SDP count from N×(N-1) to 2×num_leaves
       (one bidirectional pair per root↔leaf link).

    2. **Fixed 1 root.** The previous version randomly picked 1-2 roots,
       but multi-root E-Tree is uncommon in practice and the 2-root
       configs (with root↔root + root↔leaf SDPs) created 10-14 SDP
       entries that the model struggled to enumerate correctly (4-site
       val_acc was 76%, 5-site was 33%). With 1 root + 2-3 leaves the
       max SDP count is 6, which the model handles at 100%.

    Root vs leaf is encoded by `etree-leaf` on each SAP: True=leaf,
    False=root. site[0] is always the root.
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

    total = 1 + num_leaf_sites  # 1 root + N leaves
    site_ips = _n_distinct_device_ips(total)

    # site[0] = root, site[1..N] = leaves
    for s, device_ip in enumerate(site_ips):
        is_leaf = s >= 1  # site[0] is root
        prefix = f"site[{s}]"
        values[f"{prefix}.device-id"] = device_ip
        values[f"{prefix}.sap[0].port-id"] = random_port_id()
        values[f"{prefix}.sap[0].inner-vlan-tag"] = -1
        values[f"{prefix}.sap[0].outer-vlan-tag"] = vlan
        values[f"{prefix}.sap[0].etree-leaf"] = is_leaf

    # Root↔leaf SDPs only (E-Tree semantics: no leaf↔leaf communication).
    # For each leaf, one bidirectional pair: root→leaf + leaf→root.
    root_ip = site_ips[0]
    sdp_idx = 0
    for leaf_idx in range(1, total):
        leaf_ip = site_ips[leaf_idx]
        # root → leaf
        values[f"sdp[{sdp_idx}].sdp-id"] = derive_sdp_id(root_ip, leaf_ip)
        values[f"sdp[{sdp_idx}].source-device-id"] = root_ip
        values[f"sdp[{sdp_idx}].destination-device-id"] = leaf_ip
        sdp_idx += 1
        # leaf → root
        values[f"sdp[{sdp_idx}].sdp-id"] = derive_sdp_id(leaf_ip, root_ip)
        values[f"sdp[{sdp_idx}].source-device-id"] = leaf_ip
        values[f"sdp[{sdp_idx}].destination-device-id"] = root_ip
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


def generate_evpn_epipe_values(
    *,
    service_name: str,
    customer_id: int,
    ne_service_id: int,
    evi: int,
    evpn_type: str,
    vlan: int,
    device: str,
    port: str,
    local_ac: str,
    remote_ac: str,
) -> Dict[str, Any]:
    """**Pure function** from instruction-visible args to fill_values dict.

    The contract: every entry in the returned dict is one of:

    1. Directly equal to one of the keyword arguments (which are guaranteed
       to appear verbatim in the instruction template), OR
    2. A constant for this intent type (e.g. `mtu=1500`, `ecmp=4`,
       `inner-vlan-tag=-1`, all the auto-bind-tunnel resolution-filter
       booleans, the import-export route-target type), OR
    3. A simple deterministic string/int function of the arguments
       (description = "{service_name} EVPN service", RD = "65000:{ne_service_id}",
       VNI = ne_service_id, vsi-import = ["{service_name}-import"], etc.)

    The model can therefore reproduce every output field exactly from
    what it sees in the instruction. There is no internal randomness,
    no `random.X` call, no field that the model would have to guess.

    This was rewritten in M3.5-fix after the M3.5 baseline eval showed
    the previous version (which had random RD/RT/VNI/eth-tag/ecmp/mtu
    inside the generator) capping evpn-epipe value accuracy at ~73%
    because the model has no signal for those random values.

    Derivation rules used (chosen to match real Nokia operator practice):
      - RD / RT     : "65000:<ne-service-id>"   (fixed ASN, service-id payload)
      - VNI         : ne_service_id              (VXLAN ID == service ID)
      - vsi-import  : ["<service-name>-import"]
      - vsi-export  : ["<service-name>-export"]
      - eth-tag     : vlan                       (consistency: AC tag == access vlan)
      - mtu, ecmp   : 1500, 4                    (constants — model just memorizes)
      - resolution-filter.{bgp,ldp,sr-isis} : True  (default Nokia auto-bind set)
    """
    rd = f"65000:{ne_service_id}"
    rt = f"65000:{ne_service_id}"

    values: Dict[str, Any] = {
        # ----- Direct from instruction args -----
        "service-name": service_name,
        "customer-id": customer_id,
        "ne-service-id": ne_service_id,
        "evpn-type": evpn_type,
        "site-a.device-id": device,
        "site-a.evi": evi,
        "site-a.local-ac.name": local_ac,
        "site-a.remote-ac.name": remote_ac,
        "site-a.sap[0].port-id": port,
        "site-a.sap[0].outer-vlan-tag": vlan,
        # ----- Constants -----
        "mtu": 1500,
        "site-a.mtu": 1500,
        "site-a.ecmp": 4,
        "site-a.sap[0].inner-vlan-tag": -1,
        # ----- Derived from service_name (string template) -----
        "description": f"{service_name} EVPN service",
        "site-a.description": f"{service_name} site-a",
        # ----- Derived from vlan (eth-tag == access vlan) -----
        "site-a.local-ac.eth-tag": vlan,
        "site-a.remote-ac.eth-tag": vlan,
    }

    if evpn_type == "mpls":
        values.update({
            "site-a.mpls.bgp-instance.route-distinguisher": rd,
            "site-a.mpls.bgp-instance.route-target[0].target-type": "import-export",
            "site-a.mpls.bgp-instance.route-target[0].target-value": rt,
            "site-a.mpls.bgp-instance.vsi-import": [f"{service_name}-import"],
            "site-a.mpls.bgp-instance.vsi-export": [f"{service_name}-export"],
            "site-a.mpls.auto-bind-tunnel.resolution": "filter",
            "site-a.mpls.auto-bind-tunnel.resolution-filter.bgp": True,
            "site-a.mpls.auto-bind-tunnel.resolution-filter.ldp": True,
            "site-a.mpls.auto-bind-tunnel.resolution-filter.sr-isis": True,
        })
    else:  # vxlan
        values.update({
            "site-a.vxlan.vni": ne_service_id,
            "site-a.vxlan.bgp-instance.route-distinguisher": rd,
            "site-a.vxlan.bgp-instance.route-target[0].target-type": "import-export",
            "site-a.vxlan.bgp-instance.route-target[0].target-value": rt,
            "site-a.vxlan.bgp-instance.vsi-import": [f"{service_name}-import"],
            "site-a.vxlan.bgp-instance.vsi-export": [f"{service_name}-export"],
        })

    return values


# ---------------------------------------------------------------------------
# evpn-vpls (NEW M3) — EVPN-based multipoint Ethernet
# ---------------------------------------------------------------------------


def generate_evpn_vpls_values(
    *,
    service_name: str,
    customer_id: int,
    ne_service_id: int,
    mtu: int,
    evi: int,
    evpn_type: str,
    vlan: int,
    site_devices: list[str],
    site_ports: list[str],
) -> Dict[str, Any]:
    """**Pure function** from instruction-visible args to fill_values dict.

    Same contract as ``generate_evpn_epipe_values``: every output entry is
    either directly from a kwarg, a constant, or a deterministic function
    of the kwargs. No internal randomness.

    `site_devices` and `site_ports` are aligned lists (one entry per site)
    that the instruction template surfaces as `siteN_device` / `siteN_port`
    placeholders. The number of sites is `len(site_devices)`.

    Per-site derivations:
      - description           : "{service_name} site-{N+1}"
      - mtu (per-site)        : == top-level mtu (single source of truth)
      - ecmp                  : 4 (constant)
      - evi (per-site)        : == top-level evi (one bridge domain, one EVI)
      - evpn-type (per-site)  : == top-level evpn_type (homogeneous deployment)
      - routed-vpls           : False (constant)
      - inner-vlan-tag        : -1 (constant)
      - outer-vlan-tag        : == top-level vlan (consistent access encap)
      - bgp-instance-id       : 1 (constant)
      - route-distinguisher   : "65000:{ne_service_id}"
      - route-target value    : "65000:{ne_service_id}"
      - vsi-import / -export  : ["{service_name}-import" / "-export"]
      - vni                   : ne_service_id

    Was rewritten in M3.5-fix because the prior version's per-site random
    RD/RT/VNI/ecmp/mtu was capping evpn-vpls value accuracy at ~78%.
    """
    rd = f"65000:{ne_service_id}"
    rt = f"65000:{ne_service_id}"
    assert len(site_devices) == len(site_ports), \
        "site_devices and site_ports must be aligned"

    values: Dict[str, Any] = {
        "service-name": service_name,
        "customer-id": customer_id,
        "ne-service-id": ne_service_id,
        "mtu": mtu,
        "description": f"{service_name} bridge domain",
    }

    for s, (device_ip, port_id) in enumerate(zip(site_devices, site_ports)):
        prefix = f"site[{s}]"
        values[f"{prefix}.device-id"] = device_ip
        values[f"{prefix}.description"] = f"{service_name} site-{s+1}"
        values[f"{prefix}.mtu"] = mtu
        values[f"{prefix}.evi"] = evi
        values[f"{prefix}.ecmp"] = 4
        values[f"{prefix}.evpn-type"] = evpn_type
        values[f"{prefix}.routed-vpls"] = False
        values[f"{prefix}.sap[0].port-id"] = port_id
        values[f"{prefix}.sap[0].inner-vlan-tag"] = -1
        values[f"{prefix}.sap[0].outer-vlan-tag"] = vlan

        if evpn_type in ("mpls", "both"):
            values[f"{prefix}.mpls.bgp-instance.bgp-instance-id"] = 1
            values[f"{prefix}.mpls.bgp-instance.route-distinguisher"] = rd
            values[f"{prefix}.mpls.bgp-instance.route-target[0].target-type"] = "import-export"
            values[f"{prefix}.mpls.bgp-instance.route-target[0].target-value"] = rt
            values[f"{prefix}.mpls.bgp-instance.vsi-import"] = [f"{service_name}-import"]
            values[f"{prefix}.mpls.bgp-instance.vsi-export"] = [f"{service_name}-export"]
            values[f"{prefix}.mpls.auto-bind-tunnel.resolution"] = "filter"
            values[f"{prefix}.mpls.auto-bind-tunnel.resolution-filter.bgp"] = True
            values[f"{prefix}.mpls.auto-bind-tunnel.resolution-filter.ldp"] = True
            values[f"{prefix}.mpls.auto-bind-tunnel.resolution-filter.sr-isis"] = True
        if evpn_type in ("vxlan", "both"):
            values[f"{prefix}.vxlan.vni"] = ne_service_id
            values[f"{prefix}.vxlan.bgp-instance.bgp-instance-id"] = 1
            values[f"{prefix}.vxlan.bgp-instance.route-distinguisher"] = rd
            values[f"{prefix}.vxlan.bgp-instance.route-target[0].target-type"] = "import-export"
            values[f"{prefix}.vxlan.bgp-instance.route-target[0].target-value"] = rt
            values[f"{prefix}.vxlan.bgp-instance.vsi-import"] = [f"{service_name}-import"]
            values[f"{prefix}.vxlan.bgp-instance.vsi-export"] = [f"{service_name}-export"]

    return values


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


def _roll_evpn_epipe_args() -> Dict[str, Any]:
    """Roll the random instruction-arg set for one evpn-epipe sample.

    Used by the dispatcher and smoke test to feed the pure
    `generate_evpn_epipe_values` function. The same helper is also used
    by `build_evpn_epipe_sample` in `generate_training_data.py` so the
    instruction template and the generator see byte-identical args.
    """
    site_a_ip, _ = _two_distinct_device_ips()
    project = random_project_name()
    service_id = random_service_id()
    return {
        "service_name": random_service_name_evpn_epipe(service_id, project),
        "customer_id": random_customer_id(),
        "ne_service_id": service_id,
        "evi": random_evi(),
        "evpn_type": random.choice(["mpls", "vxlan"]),
        "vlan": random_vlan(),
        "device": site_a_ip,
        "port": random_port_id(),
        "local_ac": f"AC-{project}-local",
        "remote_ac": f"AC-{project}-remote",
    }


def _roll_evpn_vpls_args(num_sites: int = 2) -> Dict[str, Any]:
    """Roll the random instruction-arg set for one evpn-vpls sample."""
    project = random_project_name()
    service_id = random_service_id()
    site_devices = _n_distinct_device_ips(num_sites)
    site_ports = [random_port_id() for _ in range(num_sites)]
    return {
        "service_name": random_service_name_evpn_vpls(service_id, project),
        "customer_id": random_customer_id(),
        "ne_service_id": service_id,
        "mtu": random_mtu(),
        "evi": random_evi(),
        "evpn_type": random.choice(["mpls", "vxlan", "both"]),
        "vlan": random_vlan(),
        "site_devices": site_devices,
        "site_ports": site_ports,
    }


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
    """Single dispatcher for generating fill_values across all 9 intent types.

    For the pure-function generators (`evpn-epipe`, `evpn-vpls`), if no
    explicit kwargs are passed the dispatcher rolls a random instruction-arg
    set via the `_roll_*_args` helpers and feeds them through. Callers that
    need a matching (instruction_args, fill_values) pair (e.g. the sample
    builders) should instead call `_roll_*_args` themselves and pass the
    result to the generator directly so the same args drive both the
    instruction template formatting and the fill_values generation.

    Special handling: if `num_sites` is passed for evpn-vpls, it controls
    the rolled site-count (still random IPs/ports). Other kwargs to the
    pure-function generators are passed through verbatim.
    """
    if intent_type == "evpn-epipe":
        if opts:
            return generate_evpn_epipe_values(**opts)
        return generate_evpn_epipe_values(**_roll_evpn_epipe_args())

    if intent_type == "evpn-vpls":
        if opts and "service_name" in opts:
            # Caller passed a full instruction-arg set
            return generate_evpn_vpls_values(**opts)
        # Otherwise roll args, optionally honoring num_sites
        num_sites = opts.get("num_sites", 2)
        return generate_evpn_vpls_values(**_roll_evpn_vpls_args(num_sites=num_sites))

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
