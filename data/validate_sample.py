"""
Validation functions for generated training samples.
Ensures data quality before training.
"""

import re
import json


def is_valid_ipv4(ip):
    """Check if string is a valid IPv4 address."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        try:
            n = int(p)
            if n < 0 or n > 255:
                return False
        except ValueError:
            return False
    return True


def is_valid_port_id(port):
    """Check if string is a valid physical or LAG port ID."""
    physical = re.match(r'^\d+/\d+/c\d+/\d+$', port)
    lag = re.match(r'^lag-[A-Za-z0-9-]+-\d+x\d+GE$', port)
    return bool(physical or lag)


def is_valid_vlan(vlan):
    """Check VLAN tag is in valid range."""
    return isinstance(vlan, int) and 1 <= vlan <= 4094


def is_valid_rd(rd):
    """Check route distinguisher format: ASN:ID."""
    return bool(re.match(r'^\d+:\d+$', str(rd)))


def validate_epipe_sample(fill_values):
    """Validate an epipe fill_values dict. Returns (is_valid, list_of_errors)."""
    errors = []

    # Required fields
    required = [
        "service-name", "customer-id", "ne-service-id",
        "site-a.device-id", "site-a.endpoint[0].port-id", "site-a.endpoint[0].outer-vlan-tag",
        "site-b.device-id", "site-b.endpoint[0].port-id", "site-b.endpoint[0].outer-vlan-tag",
        "sdp[0].sdp-id", "sdp[0].source-device-id", "sdp[0].destination-device-id",
        "sdp[1].sdp-id", "sdp[1].source-device-id", "sdp[1].destination-device-id",
    ]
    for f in required:
        if f not in fill_values:
            errors.append(f"Missing required field: {f}")

    if errors:
        return False, errors

    fv = fill_values

    # IP validation
    for ip_field in ["site-a.device-id", "site-b.device-id",
                     "sdp[0].source-device-id", "sdp[0].destination-device-id",
                     "sdp[1].source-device-id", "sdp[1].destination-device-id"]:
        if not is_valid_ipv4(fv[ip_field]):
            errors.append(f"Invalid IP: {ip_field}={fv[ip_field]}")

    # No duplicate device IPs
    if fv["site-a.device-id"] == fv["site-b.device-id"]:
        errors.append("Site A and Site B have the same device-id")

    # Port validation
    for port_field in ["site-a.endpoint[0].port-id", "site-b.endpoint[0].port-id"]:
        if not is_valid_port_id(fv[port_field]):
            errors.append(f"Invalid port: {port_field}={fv[port_field]}")

    # VLAN validation
    for vlan_field in ["site-a.endpoint[0].outer-vlan-tag", "site-b.endpoint[0].outer-vlan-tag"]:
        if not is_valid_vlan(fv[vlan_field]):
            errors.append(f"Invalid VLAN: {vlan_field}={fv[vlan_field]}")

    # VLAN must match on both sites
    if fv["site-a.endpoint[0].outer-vlan-tag"] != fv["site-b.endpoint[0].outer-vlan-tag"]:
        errors.append("VLAN tags don't match between site-a and site-b")

    # SDP bidirectionality check
    if fv["sdp[0].source-device-id"] != fv["site-a.device-id"]:
        errors.append("SDP[0] source must equal site-a device-id")
    if fv["sdp[0].destination-device-id"] != fv["site-b.device-id"]:
        errors.append("SDP[0] destination must equal site-b device-id")
    if fv["sdp[1].source-device-id"] != fv["site-b.device-id"]:
        errors.append("SDP[1] source must equal site-b device-id (reverse)")
    if fv["sdp[1].destination-device-id"] != fv["site-a.device-id"]:
        errors.append("SDP[1] destination must equal site-a device-id (reverse)")

    return len(errors) == 0, errors


def validate_tunnel_sample(fill_values):
    """Validate a tunnel fill_values dict."""
    errors = []
    required = ["source-ne-id", "sdp-id", "destination-ne-id", "name"]

    for f in required:
        if f not in fill_values:
            errors.append(f"Missing required field: {f}")

    if errors:
        return False, errors

    fv = fill_values

    for ip_field in ["source-ne-id", "destination-ne-id"]:
        if not is_valid_ipv4(fv[ip_field]):
            errors.append(f"Invalid IP: {ip_field}={fv[ip_field]}")

    if fv["source-ne-id"] == fv["destination-ne-id"]:
        errors.append("Source and destination are the same")

    return len(errors) == 0, errors


def validate_vprn_sample(fill_values):
    """Validate a VPRN fill_values dict."""
    errors = []

    if "service-name" not in fill_values:
        errors.append("Missing service-name")
    if "customer-id" not in fill_values:
        errors.append("Missing customer-id")

    # Find all sites
    site_indices = set()
    for key in fill_values:
        m = re.match(r'^site\[(\d+)\]\.', key)
        if m:
            site_indices.add(int(m.group(1)))

    if not site_indices:
        errors.append("No sites defined")
        return False, errors

    device_ips = set()
    for s in sorted(site_indices):
        prefix = f"site[{s}]"

        # Check required site fields
        for f in ["device-id", "ne-service-id", "route-distinguisher", "site-name"]:
            if f"{prefix}.{f}" not in fill_values:
                errors.append(f"Missing {prefix}.{f}")

        device_id = fill_values.get(f"{prefix}.device-id", "")
        if device_id:
            if not is_valid_ipv4(device_id):
                errors.append(f"Invalid IP: {prefix}.device-id={device_id}")
            if device_id in device_ips:
                errors.append(f"Duplicate device-id: {device_id}")
            device_ips.add(device_id)

        rd = fill_values.get(f"{prefix}.route-distinguisher", "")
        if rd and not is_valid_rd(rd):
            errors.append(f"Invalid RD: {prefix}.route-distinguisher={rd}")

        # Check interfaces
        iface_indices = set()
        for key in fill_values:
            m = re.match(rf'^site\[{s}\]\.interface\[(\d+)\]\.', key)
            if m:
                iface_indices.add(int(m.group(1)))

        for i in sorted(iface_indices):
            ipfx = f"{prefix}.interface[{i}]"
            ip = fill_values.get(f"{ipfx}.ipv4.primary.address", "")
            if ip and not is_valid_ipv4(ip):
                errors.append(f"Invalid interface IP: {ipfx}.ipv4.primary.address={ip}")
            port = fill_values.get(f"{ipfx}.sap.port-id", "")
            if port and not is_valid_port_id(port):
                errors.append(f"Invalid port: {ipfx}.sap.port-id={port}")

    return len(errors) == 0, errors


def validate_sample(sample):
    """Validate a complete training sample dict."""
    try:
        output = json.loads(sample["output"]) if isinstance(sample["output"], str) else sample["output"]
    except (json.JSONDecodeError, KeyError):
        return False, ["Output is not valid JSON"]

    intent_type = output.get("intent_type")
    fill_values = output.get("fill_values", {})

    if intent_type == "epipe":
        return validate_epipe_sample(fill_values)
    elif intent_type == "tunnel":
        return validate_tunnel_sample(fill_values)
    elif intent_type == "vprn":
        return validate_vprn_sample(fill_values)
    else:
        return False, [f"Unknown intent type: {intent_type}"]
