"""
Fillable field definitions for each NSP intent type.
Each field has: path (dot-path notation), type, valid range/format, and whether it's required.
Values are generated respecting constraints from Sarvesh's real operational data.
"""

import random
import string

# --- Vocabulary pools for realistic name generation ---

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


def random_ip(prefix="192.168"):
    """Generate a random private IP address."""
    parts = prefix.split(".")
    while len(parts) < 4:
        if len(parts) == 3:
            parts.append(str(random.randint(1, 254)))
        else:
            parts.append(str(random.randint(0, 255)))
    return ".".join(parts)


def random_device_ip():
    """Generate a random device management IP in 192.168.x.x range."""
    return f"192.168.{random.randint(0, 255)}.{random.randint(1, 254)}"


def random_interface_ip():
    """Generate a random interface IP in common private ranges."""
    ranges = [
        lambda: f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"100.{random.randint(64,127)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"172.{random.randint(16,31)}.{random.randint(0,255)}.{random.randint(1,254)}",
    ]
    return random.choice(ranges)()


def random_physical_port():
    """Generate a random physical port ID like 1/2/c4/1."""
    slot = random.randint(1, 2)
    mda = random.randint(1, 2)
    connector = random.randint(1, 12)
    port = random.randint(1, 4)
    return f"{slot}/{mda}/c{connector}/{port}"


def random_lag_port():
    """Generate a random LAG port ID like lag-AFOR8-4x10GE."""
    prefix = random.choice(LAG_PREFIXES)
    num = random.randint(1, 12)
    speed = random.choice(["4x10GE", "2x25GE", "4x25GE", "2x100GE"])
    return f"lag-{prefix}{num}-{speed}"


def random_port_id():
    """Generate a random port ID (physical or LAG)."""
    if random.random() < 0.5:
        return random_physical_port()
    return random_lag_port()


def random_vlan():
    """Generate a random VLAN tag (1-4094)."""
    return random.randint(1, 4094)


def random_customer_id():
    """Generate a random customer ID."""
    return random.randint(1, 9999)


def random_service_id():
    """Generate a random NE service ID."""
    return random.randint(1000, 9999)


def random_mtu():
    """Generate a random MTU value."""
    return random.choice([1492, 1500, 9000, 9100, 9192, 9212, 1400, 1450])


def derive_sdp_id(src_ip, dst_ip):
    """
    Derive SDP ID from device IPs by concatenating last octets.
    Example: 192.168.0.37 + 192.168.0.16 -> '3716'
    """
    src_last = src_ip.split(".")[-1]
    dst_last = dst_ip.split(".")[-1]
    return f"{src_last}{dst_last}"


def random_route_distinguisher(service_id):
    """Generate a route distinguisher like 65008:1001."""
    asn = random.randint(64512, 65534)
    return f"{asn}:{service_id}"


def random_project_name():
    return random.choice(PROJECT_NAMES)


def random_cluster_name():
    return random.choice(CLUSTER_NAMES)


def random_interface_name():
    """Generate a realistic interface name like Delta-Cluster-Master."""
    cluster = random_cluster_name()
    role = random.choice(CLUSTER_ROLES)
    return f"{cluster}-Cluster-{role}"


def random_tunnel_name(src_ip, dst_ip):
    """Generate a tunnel name from device IPs."""
    src_short = src_ip.replace(".", "-")
    dst_short = dst_ip.replace(".", "-")
    return f"SDP-from-{src_short}-to-{dst_short}"


def random_service_name_epipe(vlan, site_a_desc, site_b_desc):
    """Generate an epipe service name."""
    return f"Epipe-VLAN-{vlan}-{site_a_desc}-to-{site_b_desc}"


def random_service_name_vprn(service_id, project):
    """Generate a VPRN service name."""
    return f"VPRN-{service_id}-{project}"


# --- Field definitions per intent type ---

EPIPE_FIELDS = {
    "service-name": {"type": "string", "required": True},
    "customer-id": {"type": "int", "min": 1, "max": 9999, "required": True},
    "ne-service-id": {"type": "int", "min": 1000, "max": 9999, "required": True},
    "mtu": {"type": "int", "values": [1400, 1450, 1492, 1500, 9000, 9100, 9192], "required": False},
    "site-a.device-id": {"type": "ip", "required": True},
    "site-a.endpoint[0].port-id": {"type": "port", "required": True},
    "site-a.endpoint[0].outer-vlan-tag": {"type": "int", "min": 1, "max": 4094, "required": True},
    "site-b.device-id": {"type": "ip", "required": True},
    "site-b.endpoint[0].port-id": {"type": "port", "required": True},
    "site-b.endpoint[0].outer-vlan-tag": {"type": "int", "min": 1, "max": 4094, "required": True},
    "sdp[0].sdp-id": {"type": "string", "required": True},
    "sdp[0].source-device-id": {"type": "ip", "required": True},
    "sdp[0].destination-device-id": {"type": "ip", "required": True},
    "sdp[1].sdp-id": {"type": "string", "required": True},
    "sdp[1].source-device-id": {"type": "ip", "required": True},
    "sdp[1].destination-device-id": {"type": "ip", "required": True},
}

TUNNEL_FIELDS = {
    "source-ne-id": {"type": "ip", "required": True},
    "sdp-id": {"type": "string", "required": True},
    "destination-ne-id": {"type": "ip", "required": True},
    "name": {"type": "string", "required": True},
}

VPRN_TOP_FIELDS = {
    "service-name": {"type": "string", "required": True},
    "customer-id": {"type": "int", "min": 1, "max": 9999, "required": True},
}

VPRN_SITE_FIELDS = {
    "site-name": {"type": "string", "required": True},
    "device-id": {"type": "ip", "required": True},
    "ne-service-id": {"type": "int", "min": 1000, "max": 9999, "required": True},
    "route-distinguisher": {"type": "string", "required": True},
    "vrf-import": {"type": "list_string", "required": True},
    "vrf-export": {"type": "list_string", "required": True},
}

VPRN_INTERFACE_FIELDS = {
    "interface-name": {"type": "string", "required": True},
    "sap.port-id": {"type": "port", "required": True},
    "ipv4.primary.address": {"type": "ip", "required": True},
    "ipv4.primary.prefix-length": {"type": "int", "values": [24, 28, 30, 31, 32], "required": True},
}


def generate_epipe_values():
    """Generate a complete set of fill values for an epipe intent."""
    site_a_ip = random_device_ip()
    site_b_ip = random_device_ip()
    while site_b_ip == site_a_ip:
        site_b_ip = random_device_ip()

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


def generate_tunnel_values():
    """Generate a complete set of fill values for a tunnel intent."""
    src_ip = random_device_ip()
    dst_ip = random_device_ip()
    while dst_ip == src_ip:
        dst_ip = random_device_ip()

    sdp_id = derive_sdp_id(src_ip, dst_ip)

    return {
        "source-ne-id": src_ip,
        "sdp-id": sdp_id,
        "destination-ne-id": dst_ip,
        "name": random_tunnel_name(src_ip, dst_ip),
    }


def generate_vprn_values(num_sites=1, interfaces_per_site=2):
    """Generate a complete set of fill values for a VPRN intent."""
    project = random_project_name()
    service_id = random_service_id()
    customer_id = random_customer_id()

    values = {
        "service-name": random_service_name_vprn(service_id, project),
        "customer-id": customer_id,
    }

    used_device_ips = set()
    for s in range(num_sites):
        device_ip = random_device_ip()
        while device_ip in used_device_ips:
            device_ip = random_device_ip()
        used_device_ips.add(device_ip)

        rd = random_route_distinguisher(service_id)
        vrf_import = f"{project}-VRF-Import"
        vrf_export = f"{project}-VRF-Export"

        values[f"site[{s}].site-name"] = random_service_name_vprn(service_id, project)
        values[f"site[{s}].device-id"] = device_ip
        values[f"site[{s}].ne-service-id"] = service_id
        values[f"site[{s}].route-distinguisher"] = rd
        values[f"site[{s}].vrf-import"] = [vrf_import]
        values[f"site[{s}].vrf-export"] = [vrf_export]

        cluster = random_cluster_name()
        used_iface_ips = set()
        for i in range(interfaces_per_site):
            role = CLUSTER_ROLES[i % len(CLUSTER_ROLES)]
            iface_name = f"{cluster}-Cluster-{role}"
            iface_ip = random_interface_ip()
            while iface_ip in used_iface_ips:
                iface_ip = random_interface_ip()
            used_iface_ips.add(iface_ip)

            prefix = f"site[{s}].interface[{i}]"
            values[f"{prefix}.interface-name"] = iface_name
            values[f"{prefix}.sap.port-id"] = random_port_id()
            values[f"{prefix}.ipv4.primary.address"] = iface_ip
            values[f"{prefix}.ipv4.primary.prefix-length"] = random.choice([24, 28, 30, 31])

    return values
