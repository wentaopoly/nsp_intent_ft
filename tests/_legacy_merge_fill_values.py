"""
Merge fill-values into NSP intent templates to produce API-ready JSON.
Uses dot-path notation with array index support.
"""

import json
import copy
import re
import os

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "templates")

TEMPLATES = {
    "epipe": "epipe_template.json",
    "tunnel": "tunnel_template.json",
    "vprn": "vprn_template.json",
}

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
    """Load and return a deep copy of the template for the given intent type."""
    filename = TEMPLATES.get(intent_type)
    if not filename:
        raise ValueError(f"Unknown intent type: {intent_type}")
    path = os.path.join(TEMPLATE_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


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


def resolve_epipe_paths(fill_values):
    """Map fill-value dot-paths to actual template JSON paths for epipe."""
    path_map = {
        "service-name": ["nsp-service-intent:intent", 0, "service-name"],
        "customer-id": ["nsp-service-intent:intent", 0, "intent-specific-data", "epipe:epipe", "customer-id"],
        "ne-service-id": ["nsp-service-intent:intent", 0, "intent-specific-data", "epipe:epipe", "ne-service-id"],
        "mtu": ["nsp-service-intent:intent", 0, "intent-specific-data", "epipe:epipe", "mtu"],
    }

    base = ["nsp-service-intent:intent", 0, "intent-specific-data", "epipe:epipe"]

    dynamic_maps = {
        "site-a.device-id": base + ["site-a", "device-id"],
        "site-a.endpoint[0].port-id": base + ["site-a", "endpoint", 0, "port-id"],
        "site-a.endpoint[0].outer-vlan-tag": base + ["site-a", "endpoint", 0, "outer-vlan-tag"],
        "site-b.device-id": base + ["site-b", "device-id"],
        "site-b.endpoint[0].port-id": base + ["site-b", "endpoint", 0, "port-id"],
        "site-b.endpoint[0].outer-vlan-tag": base + ["site-b", "endpoint", 0, "outer-vlan-tag"],
        "sdp[0].sdp-id": base + ["sdp-details", "sdp", 0, "sdp-id"],
        "sdp[0].source-device-id": base + ["sdp-details", "sdp", 0, "source-device-id"],
        "sdp[0].destination-device-id": base + ["sdp-details", "sdp", 0, "destination-device-id"],
        "sdp[1].sdp-id": base + ["sdp-details", "sdp", 1, "sdp-id"],
        "sdp[1].source-device-id": base + ["sdp-details", "sdp", 1, "source-device-id"],
        "sdp[1].destination-device-id": base + ["sdp-details", "sdp", 1, "destination-device-id"],
    }

    path_map.update(dynamic_maps)
    return path_map


def resolve_tunnel_paths(fill_values):
    """Map fill-value dot-paths to actual template JSON paths for tunnel."""
    base = ["nsp-tunnel-intent:intent", 0]
    return {
        "source-ne-id": base + ["source-ne-id"],
        "sdp-id": base + ["sdp-id"],
        "destination-ne-id": base + ["intent-specific-data", "tunnel:tunnel", "destination-ne-id"],
        "name": base + ["intent-specific-data", "tunnel:tunnel", "name"],
    }


def merge_fill_values(intent_type, fill_values):
    """
    Merge fill_values into the appropriate template.
    Returns the complete API-ready JSON.
    """
    template = load_template(intent_type)
    result = copy.deepcopy(template)

    if intent_type == "epipe":
        path_map = resolve_epipe_paths(fill_values)
        for key, value in fill_values.items():
            if key in path_map:
                set_nested(result, path_map[key], value)
            else:
                print(f"Warning: Unknown epipe field path: {key}")

    elif intent_type == "tunnel":
        path_map = resolve_tunnel_paths(fill_values)
        for key, value in fill_values.items():
            if key in path_map:
                set_nested(result, path_map[key], value)
            else:
                print(f"Warning: Unknown tunnel field path: {key}")

    elif intent_type == "vprn":
        result = _merge_vprn(result, fill_values)

    else:
        raise ValueError(f"Unknown intent type: {intent_type}")

    return result


def _merge_vprn(template, fill_values):
    """Merge VPRN fill values, dynamically creating sites and interfaces."""
    result = copy.deepcopy(template)
    intent = result["nsp-service-intent:intent"][0]

    # Top-level fields
    if "service-name" in fill_values:
        intent["service-name"] = fill_values["service-name"]
    if "customer-id" in fill_values:
        intent["intent-specific-data"]["vprn:vprn"]["customer-id"] = fill_values["customer-id"]

    # Discover sites and interfaces from fill_values
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

    sites_list = intent["intent-specific-data"]["vprn:vprn"]["site-details"]["site"]

    for si in sorted(site_indices):
        # Create site skeleton
        site = copy.deepcopy(VPRN_SITE_SKELETON)

        # Fill site-level fields
        prefix = f"site[{si}]"
        field_map = {
            "site-name": "site-name",
            "device-id": "device-id",
            "ne-service-id": "ne-service-id",
            "route-distinguisher": "route-distinguisher",
            "vrf-import": "vrf-import",
            "vrf-export": "vrf-export",
        }
        for fv_suffix, site_key in field_map.items():
            fv_key = f"{prefix}.{fv_suffix}"
            if fv_key in fill_values:
                site[site_key] = fill_values[fv_key]

        # Create interfaces
        iface_indices = sorted(site_iface_indices.get(si, []))
        for ii in iface_indices:
            iface = copy.deepcopy(VPRN_INTERFACE_SKELETON)
            ipfx = f"{prefix}.interface[{ii}]"

            iface_field_map = {
                "interface-name": ["interface-name"],
                "sap.port-id": ["sap", "port-id"],
                "ipv4.primary.address": ["ipv4", "primary", "address"],
                "ipv4.primary.prefix-length": ["ipv4", "primary", "prefix-length"],
            }
            for fv_suffix, json_path in iface_field_map.items():
                fv_key = f"{ipfx}.{fv_suffix}"
                if fv_key in fill_values:
                    obj = iface
                    for p in json_path[:-1]:
                        obj = obj[p]
                    obj[json_path[-1]] = fill_values[fv_key]

            site["interface-details"]["interface"].append(iface)

        sites_list.append(site)

    return result


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
