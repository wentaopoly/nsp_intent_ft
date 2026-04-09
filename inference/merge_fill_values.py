"""
Merge fill-values into NSP intent templates to produce API-ready JSON.
Uses dot-path notation with array index support.

Path resolution is YANG-driven via `data.yang_schema.resolve_path` (Milestone 2):
the previous hardcoded `resolve_epipe_paths` / `resolve_tunnel_paths` maps
have been removed in favour of one generic resolver that walks the official
Nokia YANG schema for the intent type.

The VPRN site / interface skeletons remain hand-coded because they encode
NSP API DEFAULTS (captured from real network responses) that are NOT YANG
defaults — they have to be provided alongside the schema-driven path
resolution. Future work will derive these from a richer source (e.g. the
canonical `documentation/payload*.ibsf.json` examples in the unified
artifact bundle) once Milestone 3 needs them for new intent types.
"""

import json
import copy
import re
import os
import sys

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "templates")

TEMPLATES = {
    "epipe": "epipe_template.json",
    "tunnel": "tunnel_template.json",
    "vprn": "vprn_template.json",
}

# Make `data/` importable so we can pull in yang_schema.resolve_path.
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
if _DATA_DIR not in sys.path:
    sys.path.insert(0, _DATA_DIR)

from yang_schema import resolve_path, intent_body_info  # noqa: E402

# VPRN site skeleton used when dynamically adding sites
VPRN_SITE_SKELETON = {
    "route-aggregation": {},
    "site-name": "",
    "enable-rip": False,
    "route-distinguisher-type": "type0",
    "bgp-evpn": {"enable-evpn-mpls": False},
    "interface-details": {"interface": []},
    "device-id": "",
    "vrf-import": [],
    "enable-isis": False,
    "ne-service-id": 0,
    "bgp-vpn-backup": {},
    "bgp-ipvpn-admin-state": "unlocked",
    "ip-transports": {},
    "enable-static-route": False,
    "ipv6": {"router-advertisement": {}},
    "enable-ospf": False,
    "auto-bind-tunnel": {
        "resolution-filter": {"bgp": True},
        "resolution": "filter",
        "enforce-strict-tunnel-tagging": False,
    },
    "vrf-export": [],
    "enable-max-routes": False,
    "enable-ebgp": False,
    "route-distinguisher": "",
    "confederation": {},
}

VPRN_INTERFACE_SKELETON = {
    "sap": {
        "enable-filter": False,
        "cpu-protection": {},
        "outer-vlan-tag": 0,
        "port-id": "",
        "admin-state": "unlocked",
        "enable-qos": False,
        "encap-type": "dot1q",
        "inner-vlan-tag": -1,
    },
    "ingress-stats": True,
    "ipv4": {
        "bfd": {},
        "neighbor-discovery": {"host-route": {}, "limit": {}},
        "icmp": {"redirects": {}, "unreachables": {}},
        "dhcp": {},
        "primary": {"prefix-length": 31, "address": ""},
    },
    "vpls": {
        "evpn": {
            "arp": {
                "advertise-dynamic": False,
                "advertise-dynamic-route-tag": 0,
                "advertise-static-route-tag": 0,
                "advertise-static": False,
                "learn-dynamic": True,
            }
        },
        "ingress": {"routed-override-filter": {}},
        "evpn-tunnel": False,
        "egress": {"routed-override-filter": {}},
    },
    "cflowd-parameters": {},
    "interface-name": "",
    "admin-state": "unlocked",
    "hold-time": {
        "ipv4": {"up": {}, "down": {"init-only": False}},
        "ipv6": {"up": {}, "down": {"init-only": False}},
    },
    "ipv6-details": {"bfd": {}, "neighbor-discovery": {}, "link-local-address": {}},
    "loopback": False,
}


def load_template(intent_type):
    """Load a deep copy of the template for the given intent type.

    For the 3 original intent types (epipe / tunnel / vprn) we have
    hand-curated JSON templates with NSP API defaults captured from real
    network responses. For all other intent types added in M3+, we
    synthesize a minimal envelope from `_INTENT_BODY_INFO` so that
    set_nested() has somewhere to write the user-provided fields.
    """
    filename = TEMPLATES.get(intent_type)
    if filename:
        path = os.path.join(TEMPLATE_DIR, filename)
        with open(path, "r") as f:
            return json.load(f)
    return _build_minimal_envelope(intent_type)


def _build_minimal_envelope(intent_type):
    """Synthesize the minimal NSP intent envelope around an empty body.

    Used by `load_template()` for any intent type that doesn't have a
    hand-curated JSON template file. The envelope shape is determined by
    `intent_body_info()` which knows whether to use `nsp-service-intent:intent`
    or `nsp-tunnel-intent:intent` and what the body container key is.
    """
    info = intent_body_info(intent_type)
    return {
        info["intent_key"]: [
            {
                "intent-type": intent_type,
                "intent-type-version": "1",
                "olc-state": "deployed",
                "template-name": f"{intent_type}-default",
                "intent-specific-data": {
                    info["body_key"]: {},
                },
            }
        ]
    }


def parse_path(dot_path):
    """
    Parse a dot-path string into a list of keys/indices.
    'site-a.endpoint[0].port-id' -> ['site-a', 'endpoint', 0, 'port-id']
    'sdp[0].sdp-id' -> ['sdp', 0, 'sdp-id']
    'site[1].interface[0].sap.port-id' -> ['site', 1, 'interface', 0, 'sap', 'port-id']
    """
    segments = []
    for part in dot_path.split("."):
        m = re.match(r'^(.+?)\[(\d+)\]$', part)
        if m:
            segments.append(m.group(1))
            segments.append(int(m.group(2)))
        else:
            segments.append(part)
    return segments


def set_nested(obj, path_segments, value):
    """Set a value in a nested dict/list structure using parsed path segments."""
    current = obj
    for i, key in enumerate(path_segments[:-1]):
        next_key = path_segments[i + 1]
        if isinstance(key, int):
            # Extend list if needed
            while len(current) <= key:
                current.append(None)
            if current[key] is None:
                current[key] = [] if isinstance(next_key, int) else {}
            current = current[key]
        else:
            if key not in current:
                current[key] = [] if isinstance(next_key, int) else {}
            current = current[key]

    last_key = path_segments[-1]
    if isinstance(last_key, int):
        while len(current) <= last_key:
            current.append(None)
        current[last_key] = value
    else:
        current[last_key] = value


def merge_fill_values(intent_type, fill_values):
    """
    Merge fill_values into the appropriate template.
    Returns the complete API-ready JSON.

    All path resolution goes through `data.yang_schema.resolve_path`, which
    walks the official Nokia YANG schema. The only intent-type-specific
    handling is the VPRN skeleton pre-population: NSP API expects each site
    and interface to carry ~25 / ~15 default fields that aren't in YANG.
    """
    template = load_template(intent_type)
    result = copy.deepcopy(template)

    # VPRN: pre-create site / interface skeletons in the merged JSON before
    # the unified set_nested loop. set_nested won't overwrite the pre-created
    # dicts; it walks into them and only sets the leaf the user specified.
    if intent_type == "vprn":
        _pre_populate_vprn_skeletons(result, fill_values)

    for key, value in fill_values.items():
        segments = resolve_path(intent_type, key)
        if segments is None:
            print(f"Warning: Unknown {intent_type} field path: {key}")
            continue
        set_nested(result, segments, value)

    return result


def _pre_populate_vprn_skeletons(result, fill_values):
    """Inject VPRN_SITE_SKELETON / VPRN_INTERFACE_SKELETON into the merged JSON
    at the right list indices, BEFORE the unified set_nested loop runs.

    This preserves NSP API default fields (admin-state, enable-rip, etc.)
    that aren't in YANG. The set_nested loop afterwards overlays
    user-provided fields on top of these skeletons.
    """
    sites_list = (
        result["nsp-service-intent:intent"][0]
        ["intent-specific-data"]["vprn:vprn"]
        ["site-details"]["site"]
    )

    # Discover which sites and interfaces are referenced by fill_values keys
    site_indices = set()
    site_iface_indices = {}
    for key in fill_values:
        m = re.match(r'^site\[(\d+)\]', key)
        if m:
            si = int(m.group(1))
            site_indices.add(si)
            im = re.match(r'^site\[\d+\]\.interface\[(\d+)\]', key)
            if im:
                site_iface_indices.setdefault(si, set()).add(int(im.group(1)))

    # Pre-create sites in sorted order. The original `_merge_vprn` used
    # sites_list.append(skeleton) for each site index in sorted order, so
    # the resulting list positions are 0..N-1 regardless of which `site[K]`
    # the user wrote. We preserve that behaviour exactly here for diff
    # equivalence with the previous implementation.
    for si in sorted(site_indices):
        site = copy.deepcopy(VPRN_SITE_SKELETON)
        sites_list.append(site)

        iface_list = site["interface-details"]["interface"]
        for ii in sorted(site_iface_indices.get(si, [])):
            iface_list.append(copy.deepcopy(VPRN_INTERFACE_SKELETON))


if __name__ == "__main__":
    # Quick test: merge the golden epipe test case
    epipe_fv = {
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

    result = merge_fill_values("epipe", epipe_fv)
    print(json.dumps(result, indent=2))
