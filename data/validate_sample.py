"""
Backwards-compatible shim around `intent_validator.py` (Milestone 2).

The original 200-line regex-based validator has been replaced by
`data/intent_validator.py`, which uses Nokia's official YANG schemas plus a
much smaller set of semantic cross-field rules. This file now exists only
to keep the original public API intact for callers that import the legacy
function names directly:

    validate_epipe_sample(fill_values)  -> (ok, errors)
    validate_tunnel_sample(fill_values) -> (ok, errors)
    validate_vprn_sample(fill_values)   -> (ok, errors)
    validate_sample(sample_dict)        -> (ok, errors)

Each shim runs Tier 1 + Tier 2 (YANG schema-shape and types) plus Tier 4
(semantic cross-field rules). The output errors list combines errors from
both tiers for backwards compatibility with the old aggregated error list.
"""

import json

try:
    from .intent_validator import validate_fill_values, validate_semantic
except ImportError:
    # Top-level import (sys.path includes data/)
    from intent_validator import validate_fill_values, validate_semantic


def _combined(intent_type, fill_values):
    ok1, errs1 = validate_fill_values(intent_type, fill_values)
    ok4, errs4 = validate_semantic(intent_type, fill_values)
    return (ok1 and ok4), errs1 + errs4


def validate_epipe_sample(fill_values):
    """Validate an epipe fill_values dict. Returns (is_valid, list_of_errors)."""
    return _combined("epipe", fill_values)


def validate_tunnel_sample(fill_values):
    """Validate a tunnel fill_values dict."""
    return _combined("tunnel", fill_values)


def validate_vprn_sample(fill_values):
    """Validate a VPRN fill_values dict."""
    return _combined("vprn", fill_values)


def validate_sample(sample):
    """Validate a complete training sample dict (output is a JSON string).

    Accepts ANY intent type that the YANG schema loader knows about
    (currently 9: epipe / tunnel / vprn / vpls / ies / etree / cpipe /
    evpn-epipe / evpn-vpls). If load_schema fails for an unknown intent
    type, _combined will surface a descriptive error.
    """
    try:
        output = json.loads(sample["output"]) if isinstance(sample["output"], str) else sample["output"]
    except (json.JSONDecodeError, KeyError):
        return False, ["Output is not valid JSON"]

    intent_type = output.get("intent_type")
    if not intent_type:
        return False, ["Missing intent_type"]

    fill_values = output.get("fill_values", {})
    return _combined(intent_type, fill_values)
