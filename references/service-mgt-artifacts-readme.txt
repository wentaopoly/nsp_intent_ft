service-mgt-artifacts-unified-nsp-23-11-0-24-8-0-cam-v2.zip:

Defects Fixed:

NSPD-327767 - In NSP IES service SAP ingress queue overrides not displaying
NSPD-327844 - Audit misaligned and pull from network failed
NSPD-328087 - EVPN-VPLS brownfield discovered service issue with wrongly configured routed-vpls attribute (empty) + audit not seeing the issue
NSPF-451728 - Modification of CEM Parameters and audit issue for brownfield Cpipe service
NSPF-455056 - False deployment status in NSP Service Management for Epipe Service SAP Ingress/Egress Queue Overrides
NSPF-455078 - Epipe Service SAP Ingress Queue Override with default QoS Policy cannot be pulled from network into NSP
NSPF-458737 - Make IXR support more robust in predefined intents

service-mgt-artifacts-unified-nsp-23-11-0-24-11-0-cam.zip:

Features Added:

NSPF-311021 - IB-SF: Support of Network spans - RBAC - Span of control (Only Supported in NSP 24.11+)

Defects Fixed:

NSPF-466500 - Tunnel Binding destination ne-id empty
NSPF-464871 - Event Timeline pulling in duplicate events due to type change
NSPF-464352 - Add evpn-vpls and evpn-epipe documentation to intent
NSPF-463710 - Anti-Spoof is misaligned on audit for SAR
NSPF-460298 - Change send communities to Disable standard send communities and regenerate gap files
NSPF-460163 - IBSF Resync NPE updateData tunnel remove far-end ip-address
NSPF-460143 - UCC15: VPRN Audit difference seen for ISIS instance
NSPF-459820 - VPRN: Authentication Key is clear text in the list window
NSPF-459280 - Brownfield Testing: Routing policies are not updated in NSP for classic nodes when pull is performed
NSPF-459226 - Brownfield Testing:VPRN Scheduler Policy Parent Weight and Cir Weight are not pulled from the network.
NSPF-459225 - Brownfield Testing:VPRN QOS- MBS override is not resynced when we do pull from the network.
NSPF-459222 - Brownfield Testing:VPRN Policer Control Policy - Audit not showing difference when overrides are present in CLI.
NSPF-456419 - REGR: Failed to delete service NullPointerException remove customer description
NSPF-450182 - Need service sources to be populated while creation of the service.
NSPD-329330 - misaligned intent for classic nodes when creating epipe from default intent
NSPD-329029 - VPLS Predefine Intent type After performing a pull from the network, the redeployment of the service results in the Removal of site from NFMP
NSPD-328714 - Service Intent Types cannot handle PXC-Ports as SAPs
NSPD-328684 - Anti-Spoof is misaligned on audit for SAR
NSPD-327880 - Pull-From-Network-Failed to the VPRN service when the prefix-limit configuration under the BGP neighbor.

service-mgt-artifacts-unified-nsp-23-11-0-24-11-0-cam-v2.zip:

Defects Fixed:

NSPF-422361 - mdm resync-fw submit resync for site with apostophe fails
NSPD-330355 - NSP IETF L2VPN implementation has issues configuring SAP Access/Ingress & QoS policies

service-mgt-artifacts-unified-nsp-23-11-0-25-04-0-cam.zip:

Defects Fixed:

NSPF-450498 - Intent deployment performance enhancment lookup node type
NSPF-XXXXXX - BGP PeerType not set conrrectly on pull from network
NSPF-461966 - Populate the RD type field based on the RD value
NSPF-XXXXXX - Routed VPLS Ingress Override Filter not deployed properly on MDSROS devices
NSPF-XXXXXX - Change ospf metric to allow 0 on VPRN intent type
NSPF-457045 - Epipe Service mandatory fields removed after removal of service configuration from end sites
NSPF-XXXXXX - PIM Snooping and ProxyND not supported on BVPLS sites

service-mgt-artifacts-unified-nsp-23-11-0-25-08-0-cam.zip:

Features Added:

NSPF-483625 - IB-SF: Critical attributes gaps to be addressed in 2025

Defects Fixed:

NSPF-480951 - EVPN-VPLS Services on IPV6 Classic SR nodes get misaligned after updates and alignments
NSPD-332173 - epipe with SAP-ingress policy fails to deploy on 7210
NSPF-493964 - IBSF vpls intent - STP Mode mismatches are not detected by service audit
NSPF-491673 - IBSF redundant-cline intent - Intent does not set "primary" precedence on SDP binding
NSPF-498130 - IBSF vpls intent - Site STP Priority value 0 is not being deployed to NFM-P / NE, AUDIT doesn't detect mismatch




