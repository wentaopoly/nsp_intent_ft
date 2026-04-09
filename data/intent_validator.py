"""
YANG-aware validator for NSP intent fill_values produced by the fine-tuned model.

This module implements four tiers of offline validation:

  Tier 1 — Path validity
      Every key in `fill_values` must correspond to a real YANG leaf path
      in the intent's official schema (with the project's wrapper-stripped
      shorthand convention applied).

  Tier 2 — Type / range / enum / pattern / length
      Each value must match its YANG leaf's type, value range, enum set,
      regex pattern(s), and string length restrictions.

  Tier 3 — Structural constraints on the merged intent JSON
      After merge_fill_values has produced the full intent body:
        - All YANG `mandatory true` leaves at the envelope level must be
          present (e.g. tunnel: name, destination-ne-id, source-ne-id, sdp-id)
        - Every list entry has its `key` fields populated
        - Lists respect their `max-elements` / `min-elements` bounds

  Tier 4 — Application semantic cross-field rules
      Logic that YANG cannot express but the project considers correctness:
        - epipe: SDP[0] source = site-a / SDP[0] dest = site-b (bidirectional)
        - epipe: VLAN tags match between site-a and site-b
        - epipe: site-a.device-id != site-b.device-id
        - tunnel: source-ne-id != destination-ne-id
        - vprn: all site device-ids are distinct

Tier 5 (`when` clause handling) and Tier 6 (canonical-payload similarity)
are deferred to Milestone 4.

Public API:
    validate_fill_values(intent_type, fill_values) -> (ok, errors)
    validate_merged_intent(intent_type, merged_json) -> (ok, errors)
    validate_semantic(intent_type, fill_values) -> (ok, errors)
    validate_full(intent_type, fill_values, merged_json=None) -> (ok, errors)

Note on validation completeness:
    NSP transforms the intent server-side via JavaScript before final
    deployment validation (see meta-info.json:mapping-engine="js-scripted").
    A `valid=True` result here is a STRUCTURAL LOWER BOUND — it means the
    output is consistent with the YANG schema, NOT that NSP will accept it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

try:
    from .yang_schema import (
        LeafMeta, SchemaIndex, load_schema,
        _envelope_fields, intent_body_info,
    )
except ImportError:
    # Allow loading as a top-level module (e.g. when sys.path includes data/)
    from yang_schema import (
        LeafMeta, SchemaIndex, load_schema,
        _envelope_fields, intent_body_info,
    )


def validate_fill_values(intent_type: str, fill_values: dict) -> Tuple[bool, List[str]]:
    """Validate a flat fill_values dict against the YANG schema for intent_type.

    Returns (ok, errors). `errors` is a list of human-readable strings; each
    entry references the offending field key.
    """
    try:
        schema = load_schema(intent_type)
    except (FileNotFoundError, RuntimeError) as exc:
        return False, [f"Schema load failed for intent_type={intent_type!r}: {exc}"]

    errors: List[str] = []

    for key, value in fill_values.items():
        # ----- Tier 1: path validity -----
        meta = schema.lookup(key)
        if meta is None:
            errors.append(f"unknown field path: {key!r}")
            continue

        # ----- Tier 2: value validation -----
        if meta.is_leaf_list:
            # Leaf-lists carry a Python list of values; check each element.
            if not isinstance(value, list):
                errors.append(f"{key}: leaf-list expects a list, got {type(value).__name__}")
                continue
            for i, elem in enumerate(value):
                err = _check_value(elem, meta)
                if err:
                    errors.append(f"{key}[{i}]: {err}")
        else:
            err = _check_value(value, meta)
            if err:
                errors.append(f"{key}: {err}")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Per-type value checkers
# ---------------------------------------------------------------------------


_INT_TYPES = {"int8", "int16", "int32", "int64"}
_UINT_TYPES = {"uint8", "uint16", "uint32", "uint64"}
_INT_BOUNDS = {
    "int8":  (-(1 << 7),  (1 << 7) - 1),
    "int16": (-(1 << 15), (1 << 15) - 1),
    "int32": (-(1 << 31), (1 << 31) - 1),
    "int64": (-(1 << 63), (1 << 63) - 1),
    "uint8":  (0, (1 << 8) - 1),
    "uint16": (0, (1 << 16) - 1),
    "uint32": (0, (1 << 32) - 1),
    "uint64": (0, (1 << 64) - 1),
}


def _check_value(value: Any, meta: LeafMeta) -> str:
    """Return an error message string if value violates meta, else ''."""
    base = meta.base_type

    if base == "boolean":
        return _check_boolean(value)

    if base in _INT_TYPES or base in _UINT_TYPES:
        return _check_integer(value, base, meta.range_expr)

    if base == "decimal64":
        return _check_decimal(value, meta.range_expr)

    if base == "string":
        return _check_string(value, meta.length_expr, meta.pattern_list)

    if base == "enumeration":
        return _check_enumeration(value, meta.enum_values or [])

    if base == "union":
        return _check_union(value, meta)

    if base == "empty":
        # YANG `empty` leaves carry no value
        if value not in (None, [None], [], {}):
            return f"empty leaf must have no value, got {value!r}"
        return ""

    # Unknown base type — accept anything that's a primitive (defensive fallback).
    if not isinstance(value, (str, int, float, bool, list, dict)):
        return f"unrecognized type {base!r} and value not a primitive"
    return ""


def _check_boolean(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return ""
    return f"expected boolean, got {type(value).__name__}={value!r}"


def _check_integer(value: Any, base: str, range_expr: str | None) -> str:
    # Accept int directly; accept str that parses cleanly to int.
    if isinstance(value, bool):  # bool is a subclass of int — reject
        return f"expected {base}, got bool"
    if isinstance(value, int):
        n = value
    elif isinstance(value, str):
        try:
            n = int(value)
        except ValueError:
            return f"expected {base}, got non-integer string {value!r}"
    else:
        return f"expected {base}, got {type(value).__name__}"

    lo, hi = _INT_BOUNDS[base]
    if not (lo <= n <= hi):
        return f"value {n} out of {base} bounds [{lo}, {hi}]"

    if range_expr and not _in_range(n, range_expr):
        return f"value {n} not in range {range_expr!r}"

    return ""


def _check_decimal(value: Any, range_expr: str | None) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return f"expected decimal64, got {value!r}"
    if range_expr and not _in_range(f, range_expr):
        return f"value {f} not in range {range_expr!r}"
    return ""


def _check_string(value: Any, length_expr: str | None, pattern_list: List[str]) -> str:
    if isinstance(value, bool):
        return f"expected string, got bool"
    # Accept ints/floats coerced to string only if no pattern is set;
    # otherwise enforce strict string type.
    if not isinstance(value, str):
        if pattern_list:
            return f"expected string, got {type(value).__name__}"
        value = str(value)

    if length_expr and not _in_range(len(value), length_expr):
        return f"length {len(value)} not in {length_expr!r}"

    for pat in pattern_list:
        try:
            if not re.fullmatch(_yang_pattern_to_python(pat), value):
                return f"value {value!r} does not match pattern {pat!r}"
        except re.error as exc:
            # If a pattern is too exotic for python re, log but don't fail.
            return f"(pattern {pat!r} unparsable: {exc}) skipping pattern check"
    return ""


def _check_enumeration(value: Any, enum_values: List[str]) -> str:
    if not isinstance(value, str):
        return f"expected enumeration string, got {type(value).__name__}"
    if value not in enum_values:
        return f"value {value!r} not in enum {enum_values!r}"
    return ""


def _check_union(value: Any, meta: LeafMeta) -> str:
    """Try each union member; pass if any accepts, else return all errors."""
    members = meta.union_types or []
    if not members:
        # Couldn't resolve members — fall back to permissive accept.
        return ""
    member_errors: List[str] = []
    for member in members:
        err = _check_value(value, member)
        if not err:
            return ""  # at least one member matched
        member_errors.append(err)
    return f"value {value!r} matches no union member ({'; '.join(member_errors)})"


# ---------------------------------------------------------------------------
# Range and pattern helpers
# ---------------------------------------------------------------------------


def _in_range(n: int | float, range_expr: str) -> bool:
    """Check whether n satisfies a YANG range/length expression.

    Examples:
        "1..100"            -> [1,100]
        "1..2147483647"
        "0|40..9198"        -> {0} ∪ [40,9198]
        "-1..600"
        "1..max"            -> [1, +infinity]
        "min..-1"           -> (-infinity, -1]
        "1..64"
    """
    for chunk in str(range_expr).split("|"):
        chunk = chunk.strip()
        if ".." in chunk:
            lo_s, hi_s = chunk.split("..", 1)
            lo = _parse_bound(lo_s.strip(), default=float("-inf"))
            hi = _parse_bound(hi_s.strip(), default=float("inf"))
            if lo <= n <= hi:
                return True
        else:
            try:
                if n == int(chunk):
                    return True
            except ValueError:
                try:
                    if n == float(chunk):
                        return True
                except ValueError:
                    continue
    return False


def _parse_bound(s: str, default: float) -> float:
    if s in ("min", ""):
        return float("-inf")
    if s == "max":
        return float("inf")
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return default


def _yang_pattern_to_python(pat: str) -> str:
    """Translate YANG XSD-style regex to Python re-compatible form.

    YANG patterns follow XML Schema regex (W3C XSD), which is mostly
    compatible with Python's `re` module but uses `\\p{N}` / `\\p{L}` Unicode
    categories that python re does not support.  We replace those with the
    closest python `\\d` / `\\w` equivalents — good enough for the cases
    that appear in Nokia YANG (mainly inside IPv4/IPv6 zone-id matching).
    """
    return (pat
            .replace(r"\p{N}", r"\d")
            .replace(r"\p{L}", r"[A-Za-z]")
            .replace(r"\p{Nd}", r"\d"))


# ---------------------------------------------------------------------------
# Tier 3 — structural validation of the merged intent JSON
# ---------------------------------------------------------------------------


def validate_merged_intent(intent_type: str, merged_json: dict) -> Tuple[bool, List[str]]:
    """Validate the FULLY MERGED intent JSON against schema structural constraints.

    Checks:
      - Required envelope: `<intent_key>` array with one entry exists.
      - Envelope-level mandatory fields are present (e.g. tunnel name).
      - Every list entry inside the body has its YANG `key` fields.
      - Every list respects its `max-elements` / `min-elements` bounds.

    Returns (ok, errors).
    """
    try:
        schema = load_schema(intent_type)
    except (FileNotFoundError, RuntimeError) as exc:
        return False, [f"Schema load failed for intent_type={intent_type!r}: {exc}"]

    try:
        body_info = intent_body_info(intent_type)
    except KeyError:
        return False, [f"Unknown intent_type {intent_type!r} (missing _INTENT_BODY_INFO entry)"]

    intent_key = body_info["intent_key"]
    body_key = body_info["body_key"]

    errors: List[str] = []

    intent_array = merged_json.get(intent_key)
    if not isinstance(intent_array, list) or not intent_array:
        return False, [f"missing or invalid root key: {intent_key}"]
    intent_obj = intent_array[0]
    if not isinstance(intent_obj, dict):
        return False, [f"{intent_key}[0] is not an object"]

    # Envelope-level mandatory check
    envelope_meta = _envelope_fields(intent_type)
    for env_name, env_meta in envelope_meta.items():
        if env_meta.mandatory and env_name not in intent_obj:
            errors.append(f"missing mandatory envelope field: {env_name}")

    # Walk the body container, checking lists
    body = intent_obj.get("intent-specific-data", {}).get(body_key)
    if isinstance(body, dict):
        _walk_for_list_checks(body, "<body>", schema, errors)
        # Body-level mandatory leaves (non-list-nested). Body container name
        # is the intent type by Nokia convention (epipe.yang -> container epipe).
        _check_body_mandatory(body, schema, intent_type, errors)

    return len(errors) == 0, errors


def _check_body_mandatory(body: dict, schema: SchemaIndex, body_container_name: str,
                          errors: List[str]) -> None:
    """Check that all `mandatory true` leaves NOT inside a list are present in body."""
    for canonical_path, meta in schema.leaves.items():
        if not meta.mandatory:
            continue
        if canonical_path.startswith("@envelope."):
            continue  # envelope-level, already handled by caller
        if "[*]" in canonical_path:
            continue  # inside a list — defer to list-entry-keyed check
        if not canonical_path.startswith(body_container_name + "."):
            continue  # belongs to another body container

        sub_parts = canonical_path[len(body_container_name) + 1:].split(".")
        cur: Any = body
        missing = False
        for part in sub_parts[:-1]:
            if not isinstance(cur, dict) or part not in cur:
                missing = True
                break
            cur = cur[part]
        if missing or not isinstance(cur, dict) or sub_parts[-1] not in cur:
            errors.append(f"missing mandatory body leaf: {canonical_path}")


def _walk_for_list_checks(node: Any, current_path: str, schema: SchemaIndex, errors: List[str]) -> None:
    """Recursively walk merged JSON, checking any list-typed values against schema.lists."""
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{current_path}.{k}"
            if isinstance(v, list) and v and isinstance(v[0], dict):
                # Probably a YANG list of entries (not a leaf-list of primitives)
                _check_list_against_schema(v, k, sub, schema, errors)
                for i, item in enumerate(v):
                    _walk_for_list_checks(item, f"{sub}[{i}]", schema, errors)
            elif isinstance(v, dict):
                _walk_for_list_checks(v, sub, schema, errors)
            # Leaf and leaf-list values are covered by Tier 1 + 2.


def _check_list_against_schema(lst: list, list_name: str, path: str,
                                schema: SchemaIndex, errors: List[str]) -> None:
    """Check max/min-elements and per-entry list-key presence for a YANG list."""
    # Suffix-match the list_name against schema.lists. Multiple matches are
    # acceptable: the YANG `endpoint` list (for example) shows up under both
    # site-a and site-b but they share the same key tuple, so any one is fine.
    candidates = [lm for p, lm in schema.lists.items()
                  if p.endswith(f".{list_name}[*]") or p == f"{list_name}[*]"]
    if not candidates:
        return  # Unknown list — Tier 1 already caught any unknown leaves under it.
    list_meta = candidates[0]

    if list_meta.max_elements is not None and len(lst) > list_meta.max_elements:
        errors.append(f"{path}: {len(lst)} entries exceeds max-elements={list_meta.max_elements}")
    if list_meta.min_elements is not None and len(lst) < list_meta.min_elements:
        errors.append(f"{path}: {len(lst)} entries below min-elements={list_meta.min_elements}")

    for i, entry in enumerate(lst):
        if not isinstance(entry, dict):
            continue
        for key_field in list_meta.keys:
            if key_field not in entry:
                errors.append(f"{path}[{i}]: missing list key {key_field!r}")


# ---------------------------------------------------------------------------
# Tier 4 — application semantic cross-field rules
# ---------------------------------------------------------------------------
#
# These rules express invariants the YANG schema cannot encode. They are the
# project's accumulated domain knowledge about what makes a network intent
# semantically correct (vs. just structurally valid).
#
# Ported from the original validate_sample.py.


_RD_RE = re.compile(r"^\d+:\d+$")


def validate_semantic(intent_type: str, fill_values: dict) -> Tuple[bool, List[str]]:
    """Cross-field semantic checks (Tier 4). Returns (ok, errors)."""
    if intent_type == "epipe":
        return _semantic_epipe(fill_values)
    if intent_type == "tunnel":
        return _semantic_tunnel(fill_values)
    if intent_type == "vprn":
        return _semantic_vprn(fill_values)
    # New intent types added in Milestone 3 will register their own rule sets here.
    return True, []


def _semantic_epipe(fv: dict) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    # Site-a / site-b devices must differ
    sa = fv.get("site-a.device-id")
    sb = fv.get("site-b.device-id")
    if sa and sb and sa == sb:
        errors.append("site-a and site-b have the same device-id")

    # VLAN tags must match between sites
    va = fv.get("site-a.endpoint[0].outer-vlan-tag")
    vb = fv.get("site-b.endpoint[0].outer-vlan-tag")
    if va is not None and vb is not None and va != vb:
        errors.append(f"site-a vlan {va} does not match site-b vlan {vb}")

    # SDP[0] / SDP[1] must form a bidirectional pair tied to site-a/site-b
    s0_src = fv.get("sdp[0].source-device-id")
    s0_dst = fv.get("sdp[0].destination-device-id")
    s1_src = fv.get("sdp[1].source-device-id")
    s1_dst = fv.get("sdp[1].destination-device-id")
    if sa and s0_src and s0_src != sa:
        errors.append(f"sdp[0].source-device-id {s0_src!r} != site-a.device-id {sa!r}")
    if sb and s0_dst and s0_dst != sb:
        errors.append(f"sdp[0].destination-device-id {s0_dst!r} != site-b.device-id {sb!r}")
    if sb and s1_src and s1_src != sb:
        errors.append(f"sdp[1].source-device-id {s1_src!r} != site-b.device-id {sb!r}")
    if sa and s1_dst and s1_dst != sa:
        errors.append(f"sdp[1].destination-device-id {s1_dst!r} != site-a.device-id {sa!r}")

    return len(errors) == 0, errors


def _semantic_tunnel(fv: dict) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    src = fv.get("source-ne-id")
    dst = fv.get("destination-ne-id")
    if src and dst and src == dst:
        errors.append("source-ne-id and destination-ne-id are the same")
    return len(errors) == 0, errors


def _semantic_vprn(fv: dict) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    # Discover sites
    site_indices = sorted({
        int(m.group(1))
        for m in (re.match(r'^site\[(\d+)\]\.', k) for k in fv)
        if m
    })

    # Distinct device-ids per site
    seen_ids: Dict[str, int] = {}
    for s in site_indices:
        dev = fv.get(f"site[{s}].device-id")
        if not dev:
            continue
        if dev in seen_ids:
            errors.append(
                f"site[{s}].device-id {dev!r} duplicates site[{seen_ids[dev]}]"
            )
        else:
            seen_ids[dev] = s

        # Route distinguisher format
        rd = fv.get(f"site[{s}].route-distinguisher")
        if rd and not _RD_RE.match(str(rd)):
            errors.append(f"site[{s}].route-distinguisher {rd!r} not in 'ASN:ID' form")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Combined "everything" validator
# ---------------------------------------------------------------------------


def validate_full(intent_type: str, fill_values: dict, merged_json: dict | None = None
                  ) -> Tuple[bool, Dict[str, List[str]]]:
    """Run all available tiers and return per-tier errors keyed by tier name.

    If `merged_json` is None, Tier 3 is skipped (caller should pass it after
    running merge_fill_values).
    """
    out: Dict[str, List[str]] = {}

    ok1, errs1 = validate_fill_values(intent_type, fill_values)
    out["tier1_2"] = errs1

    if merged_json is not None:
        ok3, errs3 = validate_merged_intent(intent_type, merged_json)
        out["tier3"] = errs3
    else:
        ok3 = True
        out["tier3"] = []

    ok4, errs4 = validate_semantic(intent_type, fill_values)
    out["tier4"] = errs4

    return (ok1 and ok3 and ok4), out


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    # Smoke test 1: a hand-built valid epipe sample
    sample = {
        "service-name": "Epipe-Test",
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
    ok, errs = validate_fill_values("epipe", sample)
    print(f"epipe valid: {ok}")
    for e in errs:
        print(f"  {e}")

    # Smoke test 2: a deliberately broken epipe sample
    bad = dict(sample)
    bad["customer-id"] = "not_an_int"
    bad["mtu"] = -5
    bad["site-a.endpoint[0].outer-vlan-tag"] = 99999
    bad["BOGUS_FIELD"] = "x"
    ok, errs = validate_fill_values("epipe", bad)
    print(f"\nbroken epipe valid: {ok}")
    for e in errs:
        print(f"  {e}")

    # Smoke test 3: tunnel
    tunnel_sample = {
        "source-ne-id": "192.168.0.16",
        "sdp-id": "1637",
        "destination-ne-id": "192.168.0.37",
        "name": "SDP-test",
    }
    ok, errs = validate_fill_values("tunnel", tunnel_sample)
    print(f"\ntunnel valid: {ok}")
    for e in errs:
        print(f"  {e}")
