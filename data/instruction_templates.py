"""
Natural language instruction templates for each NSP intent type.
Each template is a format string that will be filled with generated values.
Templates vary in style: formal, conversational, terse, partial-info.
"""

EPIPE_TEMPLATES = [
    # Formal, complete
    "Create an E-Pipe service named '{service_name}' for customer {customer_id} (NE service ID {ne_service_id}). "
    "Connect device {site_a_device} on port {site_a_port} to device {site_b_device} on port {site_b_port} "
    "using VLAN {vlan}. MTU is {mtu}. Use SDP {sdp_id_1} and {sdp_id_2}.",

    "Deploy an ePIPE service '{service_name}' with the following parameters: customer ID {customer_id}, "
    "service ID {ne_service_id}, MTU {mtu}. Site A is on device {site_a_device} port {site_a_port}, "
    "Site B is on device {site_b_device} port {site_b_port}. VLAN tag is {vlan}. "
    "SDP IDs are {sdp_id_1} (A to B) and {sdp_id_2} (B to A).",

    "Set up an E-Line point-to-point Ethernet service. Service name: '{service_name}'. "
    "Customer: {customer_id}. NE service ID: {ne_service_id}. MTU: {mtu}. "
    "Site A: device {site_a_device}, port {site_a_port}, VLAN {vlan}. "
    "Site B: device {site_b_device}, port {site_b_port}, VLAN {vlan}. "
    "Use SDP {sdp_id_1} from A to B and SDP {sdp_id_2} from B to A.",

    # Conversational
    "I need a point-to-point Ethernet connection between {site_a_device} and {site_b_device}. "
    "The service is for customer {customer_id}, called '{service_name}'. "
    "Site A uses port {site_a_port}, site B uses {site_b_port}, both on VLAN {vlan}. "
    "Service ID is {ne_service_id} and MTU should be {mtu}. SDPs are {sdp_id_1} and {sdp_id_2}.",

    "We need to set up a new E-Pipe service for customer {customer_id}. "
    "The connection goes from router {site_a_device} (port {site_a_port}) "
    "to router {site_b_device} (port {site_b_port}) on VLAN {vlan}. "
    "Name it '{service_name}', service ID {ne_service_id}, MTU {mtu}. "
    "Please use SDP IDs {sdp_id_1} and {sdp_id_2} for the tunnel.",

    "Can you create an epipe service? I need to connect {site_a_device} to {site_b_device}. "
    "Customer ID is {customer_id}, service name '{service_name}'. "
    "Port {site_a_port} on site A, port {site_b_port} on site B, VLAN {vlan}. "
    "NE service ID {ne_service_id}, MTU {mtu}, SDPs {sdp_id_1} and {sdp_id_2}.",

    "Please provision an E-Pipe between two routers. Details: "
    "Name='{service_name}', Customer={customer_id}, ServiceID={ne_service_id}, MTU={mtu}. "
    "Router A ({site_a_device}) port {site_a_port} VLAN {vlan}, "
    "Router B ({site_b_device}) port {site_b_port} VLAN {vlan}. "
    "SDP {sdp_id_1} for A→B, SDP {sdp_id_2} for B→A.",

    # Terse/operational
    "Deploy epipe: {service_name}, cust={customer_id}, svc-id={ne_service_id}, mtu={mtu}, "
    "{site_a_device}:{site_a_port} <-> {site_b_device}:{site_b_port}, "
    "VLAN {vlan}, SDP {sdp_id_1}/{sdp_id_2}",

    "epipe '{service_name}' customer {customer_id} ne-svc-id {ne_service_id} mtu {mtu} "
    "site-a {site_a_device} port {site_a_port} site-b {site_b_device} port {site_b_port} "
    "vlan {vlan} sdp {sdp_id_1} {sdp_id_2}",

    "New E-Pipe: '{service_name}' | Cust: {customer_id} | SvcID: {ne_service_id} | MTU: {mtu} | "
    "A: {site_a_device} {site_a_port} | B: {site_b_device} {site_b_port} | VLAN: {vlan} | "
    "SDP: {sdp_id_1}, {sdp_id_2}",

    # With context/reasoning
    "Our customer (ID: {customer_id}) needs a dedicated Layer 2 connection between their "
    "{site_a_device} and {site_b_device} routers. Please create an E-Pipe service named "
    "'{service_name}' with service ID {ne_service_id}. Use VLAN {vlan} on ports "
    "{site_a_port} (site A) and {site_b_port} (site B). MTU should be {mtu}. "
    "The SDP tunnel IDs are {sdp_id_1} and {sdp_id_2}.",

    "For the network upgrade project, provision an epipe service '{service_name}'. "
    "Customer {customer_id} requires a point-to-point connection. "
    "Source router: {site_a_device}, port: {site_a_port}. "
    "Destination router: {site_b_device}, port: {site_b_port}. "
    "Common VLAN: {vlan}. Service ID: {ne_service_id}. MTU: {mtu}. "
    "Use existing SDPs {sdp_id_1} and {sdp_id_2}.",

    # Without explicit SDP (model should still derive them)
    "Create epipe '{service_name}' for customer {customer_id} connecting "
    "{site_a_device} (port {site_a_port}) to {site_b_device} (port {site_b_port}) "
    "on VLAN {vlan}. Service ID: {ne_service_id}, MTU: {mtu}. "
    "SDP IDs: {sdp_id_1} and {sdp_id_2}.",

    "I want to deploy an E-Line service. Name: '{service_name}'. "
    "Connect customer {customer_id}'s sites: "
    "Site A at {site_a_device} using port {site_a_port}, "
    "Site B at {site_b_device} using port {site_b_port}. "
    "VLAN {vlan}, NE service ID {ne_service_id}, MTU {mtu}. "
    "SDPs: {sdp_id_1} (forward) and {sdp_id_2} (reverse).",

    "Provision E-Pipe connection: service '{service_name}', "
    "for customer ID {customer_id} with NE service ID {ne_service_id}. "
    "Site A on {site_a_device} at port {site_a_port}, "
    "Site B on {site_b_device} at port {site_b_port}, "
    "tagged with VLAN {vlan}. MTU: {mtu}. "
    "Bidirectional SDPs: {sdp_id_1}, {sdp_id_2}.",
]


TUNNEL_TEMPLATES = [
    # Formal
    "Create an MPLS tunnel from {source_device} to {dest_device} with SDP ID {sdp_id}. "
    "Name it '{tunnel_name}'. Use BGP signaling with TLDP.",

    "Deploy a service tunnel named '{tunnel_name}' connecting source device {source_device} "
    "to destination device {dest_device}. SDP ID is {sdp_id}. Transport type: MPLS, signaling: TLDP.",

    "Set up an MPLS tunnel with BGP control plane. Source NE: {source_device}, "
    "Destination NE: {dest_device}. SDP ID: {sdp_id}. Tunnel name: '{tunnel_name}'.",

    "Provision a new SDP tunnel between {source_device} and {dest_device}. "
    "Assign SDP ID {sdp_id} and name '{tunnel_name}'. "
    "Use MPLS transport with TLDP signaling and BGP tunnel enabled.",

    # Conversational
    "I need an SDP tunnel between routers {source_device} and {dest_device}. "
    "Use BGP signaling with SDP ID {sdp_id}. Name it '{tunnel_name}'.",

    "Can you create a tunnel from {source_device} to {dest_device}? "
    "SDP ID should be {sdp_id}, and call it '{tunnel_name}'. MPLS with BGP.",

    "We need a service tunnel for the connectivity between {source_device} and {dest_device}. "
    "Please use SDP ID {sdp_id} and name the tunnel '{tunnel_name}'.",

    "Please set up an MPLS tunnel. The source router is {source_device} and the destination "
    "is {dest_device}. SDP ID: {sdp_id}. Name: '{tunnel_name}'.",

    "Our network requires a new tunnel from {source_device} to {dest_device} for service transport. "
    "SDP ID is {sdp_id}. Let's call it '{tunnel_name}'. Use BGP-based MPLS.",

    # Terse
    "Deploy tunnel: src={source_device}, dst={dest_device}, sdp={sdp_id}, "
    "name='{tunnel_name}', transport=mpls, signaling=tldp",

    "tunnel '{tunnel_name}' from {source_device} to {dest_device} sdp {sdp_id} mpls bgp",

    "New SDP tunnel: {source_device} -> {dest_device} | SDP: {sdp_id} | Name: '{tunnel_name}' | MPLS/TLDP/BGP",

    # With context
    "For the new service deployment, we need an MPLS tunnel between routers "
    "{source_device} and {dest_device}. Assign SDP ID {sdp_id} and name it '{tunnel_name}'. "
    "Enable BGP tunnel with TLDP signaling.",

    "Before creating the E-Pipe service, set up the underlying MPLS tunnel. "
    "Source: {source_device}, Destination: {dest_device}. "
    "SDP ID: {sdp_id}. Name: '{tunnel_name}'.",

    "Create SDP {sdp_id} as an MPLS tunnel from {source_device} to {dest_device}. "
    "The tunnel should be named '{tunnel_name}' and use BGP-based forwarding with TLDP.",
]


VPRN_TEMPLATES_1SITE = [
    # Formal, single site
    "Create a VPRN L3 VPN service named '{service_name}' for customer {customer_id}. "
    "Configure site on device {site0_device} with service ID {site0_svc_id}. "
    "Route distinguisher: {site0_rd}. VRF policies: import {site0_vrf_import}, export {site0_vrf_export}. "
    "Interfaces: {interfaces_desc}.",

    "Deploy L3 VPN '{service_name}' for customer {customer_id}. "
    "Single site on device {site0_device}, NE service ID {site0_svc_id}. "
    "RD: {site0_rd}. Import policy: {site0_vrf_import}, export policy: {site0_vrf_export}. "
    "Configure the following interfaces: {interfaces_desc}.",

    "Set up a VPRN service '{service_name}' with one site. "
    "Customer ID: {customer_id}. Device: {site0_device}. "
    "Service ID: {site0_svc_id}. Route distinguisher: {site0_rd}. "
    "VRF import: {site0_vrf_import}, VRF export: {site0_vrf_export}. "
    "Interfaces: {interfaces_desc}.",

    # Conversational
    "I need a Layer 3 VPN for customer {customer_id}. Name it '{service_name}'. "
    "There's one site on device {site0_device} with service ID {site0_svc_id}. "
    "Use RD {site0_rd}, import policy {site0_vrf_import} and export policy {site0_vrf_export}. "
    "The interfaces are: {interfaces_desc}.",

    "Can you provision a VPRN called '{service_name}'? Customer {customer_id} has a single site "
    "on {site0_device}. Service ID is {site0_svc_id}, RD is {site0_rd}. "
    "VRF policies: {site0_vrf_import}/{site0_vrf_export}. "
    "Set up interfaces: {interfaces_desc}.",

    "We need a new L3 VPN service for customer {customer_id}. "
    "The service is called '{service_name}' with one site at {site0_device}. "
    "NE service ID: {site0_svc_id}. RD: {site0_rd}. "
    "VRF import: {site0_vrf_import}, export: {site0_vrf_export}. "
    "Please configure these interfaces: {interfaces_desc}.",

    # Terse
    "vprn '{service_name}' cust={customer_id} device={site0_device} svc-id={site0_svc_id} "
    "rd={site0_rd} vrf-import={site0_vrf_import} vrf-export={site0_vrf_export} "
    "interfaces: {interfaces_desc}",

    "Deploy VPRN: {service_name} | Customer: {customer_id} | Site: {site0_device} | "
    "SvcID: {site0_svc_id} | RD: {site0_rd} | VRF: {site0_vrf_import}/{site0_vrf_export} | "
    "{interfaces_desc}",

    # With context
    "For the {project_name} project, create a VPRN L3 VPN named '{service_name}'. "
    "Customer {customer_id} requires connectivity on device {site0_device} "
    "with service ID {site0_svc_id}. Route distinguisher: {site0_rd}. "
    "Import policy: {site0_vrf_import}, export: {site0_vrf_export}. "
    "Interfaces needed: {interfaces_desc}.",

    "Provision L3 VPN '{service_name}' for the new deployment. "
    "Customer: {customer_id}. Single site at router {site0_device}. "
    "Service ID {site0_svc_id}, RD {site0_rd}. "
    "VRF: import={site0_vrf_import}, export={site0_vrf_export}. "
    "Configure: {interfaces_desc}.",
]


VPRN_TEMPLATES_2SITE = [
    # Formal, two sites
    "Create a VPRN L3 VPN service named '{service_name}' for customer {customer_id} "
    "with two sites. Site 1 on device {site0_device} (service ID {site0_svc_id}, "
    "RD {site0_rd}, VRF {site0_vrf_import}/{site0_vrf_export}): {site0_interfaces_desc}. "
    "Site 2 on device {site1_device} (service ID {site1_svc_id}, "
    "RD {site1_rd}, VRF {site1_vrf_import}/{site1_vrf_export}): {site1_interfaces_desc}.",

    "Deploy a multi-site VPRN '{service_name}' for customer {customer_id}. "
    "First site: {site0_device}, NE SvcID {site0_svc_id}, RD {site0_rd}, "
    "VRF import {site0_vrf_import}, export {site0_vrf_export}. Interfaces: {site0_interfaces_desc}. "
    "Second site: {site1_device}, NE SvcID {site1_svc_id}, RD {site1_rd}, "
    "VRF import {site1_vrf_import}, export {site1_vrf_export}. Interfaces: {site1_interfaces_desc}.",

    # Conversational
    "I need a VPRN L3 VPN named '{service_name}' for customer {customer_id} spanning two sites. "
    "The first site is on {site0_device} with service ID {site0_svc_id} and RD {site0_rd}. "
    "VRF policies: {site0_vrf_import}/{site0_vrf_export}. Interfaces: {site0_interfaces_desc}. "
    "The second site is on {site1_device} with service ID {site1_svc_id} and RD {site1_rd}. "
    "VRF policies: {site1_vrf_import}/{site1_vrf_export}. Interfaces: {site1_interfaces_desc}.",

    "We need to provision a two-site L3 VPN for customer {customer_id}. "
    "Service name: '{service_name}'. "
    "Site A at {site0_device}: svc-id {site0_svc_id}, RD {site0_rd}, "
    "VRF {site0_vrf_import}/{site0_vrf_export}, interfaces: {site0_interfaces_desc}. "
    "Site B at {site1_device}: svc-id {site1_svc_id}, RD {site1_rd}, "
    "VRF {site1_vrf_import}/{site1_vrf_export}, interfaces: {site1_interfaces_desc}.",

    "Can you create VPRN '{service_name}' connecting two customer sites? Customer ID: {customer_id}. "
    "Device {site0_device} has service ID {site0_svc_id}, RD {site0_rd}, "
    "VRF import/export: {site0_vrf_import}/{site0_vrf_export}. Interfaces: {site0_interfaces_desc}. "
    "Device {site1_device} has service ID {site1_svc_id}, RD {site1_rd}, "
    "VRF import/export: {site1_vrf_import}/{site1_vrf_export}. Interfaces: {site1_interfaces_desc}.",

    # Terse
    "vprn '{service_name}' cust={customer_id} "
    "site0: {site0_device} svc-id={site0_svc_id} rd={site0_rd} vrf={site0_vrf_import}/{site0_vrf_export} {site0_interfaces_desc} "
    "site1: {site1_device} svc-id={site1_svc_id} rd={site1_rd} vrf={site1_vrf_import}/{site1_vrf_export} {site1_interfaces_desc}",

    # With context
    "For the {project_name} project, deploy a VPRN named '{service_name}' for customer {customer_id}. "
    "Two sites needed: "
    "Site 1 ({site0_device}): service ID {site0_svc_id}, RD {site0_rd}, "
    "VRF {site0_vrf_import}/{site0_vrf_export}, interfaces: {site0_interfaces_desc}. "
    "Site 2 ({site1_device}): service ID {site1_svc_id}, RD {site1_rd}, "
    "VRF {site1_vrf_import}/{site1_vrf_export}, interfaces: {site1_interfaces_desc}.",

    "Provision multi-site VPRN '{service_name}' | Customer: {customer_id} | "
    "Site1: {site0_device} SvcID={site0_svc_id} RD={site0_rd} VRF={site0_vrf_import}/{site0_vrf_export} {site0_interfaces_desc} | "
    "Site2: {site1_device} SvcID={site1_svc_id} RD={site1_rd} VRF={site1_vrf_import}/{site1_vrf_export} {site1_interfaces_desc}",
]


def format_interfaces_desc(values, site_idx, num_interfaces):
    """Format interface descriptions for a given site from fill values."""
    parts = []
    for i in range(num_interfaces):
        prefix = f"site[{site_idx}].interface[{i}]"
        name = values.get(f"{prefix}.interface-name", "")
        port = values.get(f"{prefix}.sap.port-id", "")
        ip = values.get(f"{prefix}.ipv4.primary.address", "")
        pfx = values.get(f"{prefix}.ipv4.primary.prefix-length", 31)
        parts.append(f"{name} on port {port} with IP {ip}/{pfx}")
    return "; ".join(parts)
