"""
Value generator registry for NSP intent fill_values (Milestone 3).

Holds Sarvesh's hand-crafted "realistic" value generators for known field
patterns plus a fallback that synthesizes a syntactically valid value from a
YANG `LeafMeta` when no domain-specific generator is registered. The
generators here are the SOURCE OF DOMAIN KNOWLEDGE that the YANG schema
itself does not encode (LAG naming convention, Nokia cluster naming, project
name pool, etc.).

Architecture:
  - vocab pools (CLUSTER_NAMES, PROJECT_NAMES, etc.)
  - low-level random_* generators (return single values, no context needed)
  - ENDING_REGISTRY: dict mapping leaf-path suffix -> generator function
  - find_generator(intent_type, dot_path) -> callable | None
  - synthesize_from_meta(LeafMeta, ...) -> value | None
  - generate_value(intent_type, dot_path, meta, context) -> value | None
      Single entry point used by field_definitions.generate_intent_values().

Design rules:
  1. Generators ALWAYS return values that pass the intent_validator's
     Tier 1+2 check for the target leaf. The synthesize_from_meta fallback
     respects YANG type, range, enum, length, and pattern.
  2. Generators that need context (service-id, project name, etc.) take a
     dict argument; those that don't, take no arguments.
  3. The registry prefers MORE SPECIFIC patterns (longer suffix) over more
     general ones, so that e.g. `ipv4.primary.prefix-length` doesn't get
     captured by a generic `prefix-length` rule.
  4. Returning None signals "skip this field" (the orchestrator may then
     leave the leaf at its YANG default or omit it from fill_values).
"""

from __future__ import annotations

import random
import re
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Vocabulary pools (Sarvesh's domain knowledge — preserved verbatim from
# the original field_definitions.py)
# ---------------------------------------------------------------------------

CLUSTER_NAMES = [
    "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta",
    "Iota", "Kappa", "Lambda", "Omega", "Saturn", "Jupiter", "Mars",
    "Neptune", "Mercury", "Venus", "Pluto", "Apollo", "Atlas", "Orion",
    "Phoenix", "Titan", "Nova", "Nebula", "Quasar", "Pulsar", "Vega",
    "Sirius", "Rigel", "Altair", "Deneb", "Polaris", "Castor",
]

CLUSTER_ROLES = [
    "Master", "Worker-1", "Worker-2", "Worker-3",
    "NAS1", "NAS2", "Storage", "Compute-1", "Compute-2",
    "GPU-1", "GPU-2", "Controller", "Edge-1", "Edge-2",
]

PROJECT_NAMES = [
    "OurAI", "NetFlow", "CloudX", "DataHub", "EdgeNet", "CoreLink",
    "SmartGrid", "TeleOps", "NetSync", "HyperNet", "VirtualNet",
    "CyberLink", "AutoNet", "FastTrack", "DeepRoute", "PathFinder",
    "WaveLink", "StarNet", "FiberX", "QuantumNet", "NexGen",
    "OptiRoute", "FlexNet", "SwiftLink", "PrimeNet", "UltraPath",
]

LAG_PREFIXES = [
    "AFOR", "Dell-NAR", "HPE", "Cisco", "Juniper", "Nokia",
    "Arista", "Mellanox", "Broadcom", "Intel", "AMD",
]

SITE_DESCRIPTIONS = [
    "datacenter", "office", "campus", "lab", "branch", "headquarters",
    "colo", "edge-site", "remote-site", "pop", "hub",
]


# ---------------------------------------------------------------------------
# Low-level random_* generators
# ---------------------------------------------------------------------------


def random_device_ip() -> str:
    """Random device management IP in 192.168.x.x range."""
    return f"192.168.{random.randint(0, 255)}.{random.randint(1, 254)}"


def random_interface_ip() -> str:
    """Random interface IP in common private ranges."""
    ranges = [
        lambda: f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        lambda: f"100.{random.randint(64, 127)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        lambda: f"172.{random.randint(16, 31)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
    ]
    return random.choice(ranges)()


def random_physical_port() -> str:
    """Physical port like 1/2/c4/1."""
    slot = random.randint(1, 2)
    mda = random.randint(1, 2)
    connector = random.randint(1, 12)
    port = random.randint(1, 4)
    return f"{slot}/{mda}/c{connector}/{port}"


def random_lag_port() -> str:
    """LAG port like lag-AFOR8-4x10GE."""
    prefix = random.choice(LAG_PREFIXES)
    num = random.randint(1, 12)
    speed = random.choice(["4x10GE", "2x25GE", "4x25GE", "2x100GE"])
    return f"lag-{prefix}{num}-{speed}"


def random_port_id() -> str:
    """Port ID — physical or LAG, ~50/50."""
    return random_physical_port() if random.random() < 0.5 else random_lag_port()


def random_vlan() -> int:
    """VLAN tag in 1..4094."""
    return random.randint(1, 4094)


def random_inner_vlan_tag() -> int:
    """Inner VLAN tag — usually -1 (no inner tag)."""
    return -1 if random.random() < 0.85 else random.randint(1, 4094)


def random_customer_id() -> int:
    """Customer ID 1..9999."""
    return random.randint(1, 9999)


def random_service_id() -> int:
    """NE service ID 1000..9999."""
    return random.randint(1000, 9999)


def random_mtu() -> int:
    """MTU sampled from common values."""
    return random.choice([1492, 1500, 9000, 9100, 9192, 9212, 1400, 1450])


def random_route_distinguisher_with_id(service_id: int) -> str:
    """Route distinguisher in ASN:service-id form."""
    asn = random.randint(64512, 65534)
    return f"{asn}:{service_id}"


def random_route_distinguisher() -> str:
    """Route distinguisher with a random service-id."""
    return random_route_distinguisher_with_id(random_service_id())


def random_route_target() -> str:
    """Route target in ASN:value form (BGP extended community)."""
    asn = random.randint(64512, 65534)
    return f"{asn}:{random.randint(1, 9999)}"


def random_project_name() -> str:
    return random.choice(PROJECT_NAMES)


def random_cluster_name() -> str:
    return random.choice(CLUSTER_NAMES)


def random_interface_name() -> str:
    """Cluster-style interface name like Delta-Cluster-Master."""
    cluster = random_cluster_name()
    role = random.choice(CLUSTER_ROLES)
    return f"{cluster}-Cluster-{role}"


def random_tunnel_name(src_ip: str, dst_ip: str) -> str:
    src_short = src_ip.replace(".", "-")
    dst_short = dst_ip.replace(".", "-")
    return f"SDP-from-{src_short}-to-{dst_short}"


def derive_sdp_id(src_ip: str, dst_ip: str) -> str:
    """SDP id derived from concatenated last octets of src/dst IPs."""
    return f"{src_ip.split('.')[-1]}{dst_ip.split('.')[-1]}"


def random_service_name_epipe(vlan: int, site_a_desc: str, site_b_desc: str) -> str:
    return f"Epipe-VLAN-{vlan}-{site_a_desc}-to-{site_b_desc}"


def random_service_name_vprn(service_id: int, project: str) -> str:
    return f"VPRN-{service_id}-{project}"


def random_service_name_vpls(service_id: int, project: str) -> str:
    return f"VPLS-{service_id}-{project}"


def random_service_name_ies(service_id: int, project: str) -> str:
    return f"IES-{service_id}-{project}"


def random_service_name_etree(service_id: int, project: str) -> str:
    return f"ETree-{service_id}-{project}"


def random_service_name_cpipe(service_id: int, project: str) -> str:
    return f"Cpipe-{service_id}-{project}"


def random_service_name_evpn_epipe(service_id: int, project: str) -> str:
    return f"EVPN-Epipe-{service_id}-{project}"


def random_service_name_evpn_vpls(service_id: int, project: str) -> str:
    return f"EVPN-VPLS-{service_id}-{project}"


def random_evi() -> int:
    """EVPN instance number (typical 1..65535)."""
    return random.randint(1, 65535)


# ---------------------------------------------------------------------------
# Path-suffix-based registry: leaf path -> generator
# ---------------------------------------------------------------------------
#
# Each entry is `(suffix, generator)` where `suffix` is matched against the
# tail of the canonical YANG path (segments joined with `.`). Suffix matching
# uses dot-segment alignment so e.g. `device-id` matches the last segment
# `device-id`, but does NOT match `something-device-id`.

# We use an ORDERED list and walk longest-first so that more specific
# patterns (e.g. `ipv4.primary.address`) take precedence over generic ones.

_REGISTRY: List[tuple[str, Callable[[], Any]]] = [
    # Most specific first
    ("ipv4.primary.address",       random_interface_ip),
    ("ipv4.primary.prefix-length", lambda: random.choice([24, 28, 30, 31, 32])),
    ("interface-details.interface[*].interface-name", random_interface_name),
    ("sap.port-id",                random_port_id),
    ("endpoint[*].port-id",        random_port_id),
    ("endpoint[*].outer-vlan-tag", random_vlan),
    ("endpoint[*].inner-vlan-tag", random_inner_vlan_tag),
    ("sdp[*].source-device-id",    random_device_ip),
    ("sdp[*].destination-device-id", random_device_ip),
    ("source-device-id",           random_device_ip),
    ("destination-device-id",      random_device_ip),
    ("source-ne-id",               random_device_ip),
    ("destination-ne-id",          random_device_ip),
    ("device-id",                  random_device_ip),
    ("interface-name",             random_interface_name),
    ("port-id",                    random_port_id),
    ("outer-vlan-tag",             random_vlan),
    ("inner-vlan-tag",             random_inner_vlan_tag),
    ("vlan-vc-tag",                random_vlan),
    ("customer-id",                random_customer_id),
    ("ne-service-id",              random_service_id),
    ("mtu",                        random_mtu),
    ("service-mtu",                random_mtu),
    ("ip-mtu",                     random_mtu),
    ("route-distinguisher",        random_route_distinguisher),
]


def find_generator(intent_type: str, dot_path: str) -> Optional[Callable[[], Any]]:
    """Look up a generator for `dot_path`. Returns None if no match."""
    # Normalize: strip wrapper containers (`*-details.`) and concrete indices,
    # then walk the registry longest-suffix-first.
    norm = re.sub(r"\[\d+\]", "[*]", dot_path)
    for suffix, fn in _REGISTRY:
        if norm == suffix or norm.endswith("." + suffix):
            return fn
    return None


# ---------------------------------------------------------------------------
# YANG-meta fallback: synthesize a value from LeafMeta type/range/enum
# ---------------------------------------------------------------------------


_INT_BASES = {"int8", "int16", "int32", "int64",
               "uint8", "uint16", "uint32", "uint64"}
_INT_RANGE_DEFAULT = {
    "int8":   (-(1 << 7), (1 << 7) - 1),
    "int16":  (-(1 << 15), (1 << 15) - 1),
    "int32":  (-(1 << 31), (1 << 31) - 1),
    "int64":  (-(1 << 63), (1 << 63) - 1),
    "uint8":  (0, (1 << 8) - 1),
    "uint16": (0, (1 << 16) - 1),
    "uint32": (0, (1 << 32) - 1),
    "uint64": (0, (1 << 64) - 1),
}


def _parse_first_range(expr: Optional[str], lo_default: int, hi_default: int) -> tuple[int, int]:
    """Parse the first sub-range of a YANG range expression like '1..100|200..300'."""
    if not expr:
        return lo_default, hi_default
    chunk = str(expr).split("|")[0].strip()
    if ".." in chunk:
        lo_s, hi_s = chunk.split("..", 1)
        lo = lo_default if lo_s.strip() in ("min", "") else _to_int_safe(lo_s.strip(), lo_default)
        hi = hi_default if hi_s.strip() in ("max", "") else _to_int_safe(hi_s.strip(), hi_default)
        return lo, hi
    try:
        v = int(chunk)
        return v, v
    except ValueError:
        return lo_default, hi_default


def _to_int_safe(s: str, fallback: int) -> int:
    try:
        return int(s)
    except ValueError:
        return fallback


def synthesize_from_meta(meta) -> Optional[Any]:
    """Generate a syntactically valid value from a YANG LeafMeta.

    Returns None when the leaf type is too unconstrained to produce a
    meaningful value (e.g. a free-form string with no length / pattern).
    The orchestrator interprets None as "skip this field".
    """
    base = meta.base_type

    if base == "boolean":
        return random.choice([True, False])

    if base == "enumeration":
        if meta.enum_values:
            return random.choice(meta.enum_values)
        return None

    if base in _INT_BASES:
        lo_d, hi_d = _INT_RANGE_DEFAULT[base]
        lo, hi = _parse_first_range(meta.range_expr, lo_d, hi_d)
        # Clamp to a sane positive sub-range when the YANG range is huge.
        if hi - lo > 100000:
            hi = min(hi, max(lo + 1, 9999))
        return random.randint(lo, hi)

    if base == "decimal64":
        return None  # rare, no clean default

    if base == "string":
        # Strings without pattern / length restrictions are too open-ended;
        # skip them rather than emitting random gibberish that confuses the
        # model. The training data orchestrator can fill description-like
        # fields with intentional sentinel values when desired.
        return None

    if base == "union":
        for member in (meta.union_types or []):
            v = synthesize_from_meta(member)
            if v is not None:
                return v
        return None

    if base == "empty":
        return None

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_value(intent_type: str, dot_path: str, meta, context: Optional[Dict] = None) -> Optional[Any]:
    """Produce a value for `dot_path` in `intent_type`.

    Lookup order:
        1. Domain-specific registry (find_generator) — Sarvesh's hand-crafted
           naming patterns and value distributions.
        2. YANG-meta synthesis (synthesize_from_meta) — type-correct fallback
           that uses range / enum from the schema.
        3. None — caller will skip the field.
    """
    fn = find_generator(intent_type, dot_path)
    if fn is not None:
        try:
            return fn()
        except TypeError:
            # Generator may take a context dict (rare)
            return fn(context or {})
    return synthesize_from_meta(meta)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    from yang_schema import load_schema

    # 1. Quick check that registry generators produce sane values
    print("=== Direct registry generators ===")
    for name in ("random_device_ip", "random_port_id", "random_vlan",
                 "random_customer_id", "random_service_id", "random_mtu",
                 "random_interface_name", "random_route_distinguisher"):
        fn = globals()[name]
        print(f"  {name:<30}: {fn()}")

    # 2. find_generator on representative paths
    print("\n=== find_generator on common paths ===")
    paths = [
        ("epipe",  "site-a.endpoint[0].port-id"),
        ("epipe",  "sdp[0].source-device-id"),
        ("vprn",   "site[0].interface[0].sap.port-id"),
        ("vprn",   "site[0].interface[0].ipv4.primary.address"),
        ("vprn",   "site[0].route-distinguisher"),
        ("tunnel", "destination-ne-id"),
        ("vpls",   "customer-id"),
        ("ies",    "site[0].device-id"),
    ]
    for it, p in paths:
        fn = find_generator(it, p)
        sample = fn() if fn else None
        print(f"  {it}::{p:<55} → {sample}")

    # 3. synthesize_from_meta on every YANG enum / int leaf for vprn (sample)
    print("\n=== synthesize_from_meta on a few YANG leaves ===")
    schema = load_schema("vprn")
    sampled = 0
    for path, m in schema.leaves.items():
        if m.base_type in ("enumeration", "uint32", "int32", "boolean") and sampled < 6:
            v = synthesize_from_meta(m)
            print(f"  {path[:60]:<60} ({m.base_type}): {v}")
            sampled += 1
