"""
YANG-aware validator for NSP intent fill_values produced by the fine-tuned model.

This module implements two tiers of offline validation:

  Tier 1 — Path validity
      Every key in `fill_values` must correspond to a real YANG leaf path
      in the intent's official schema (with the project's wrapper-stripped
      shorthand convention applied).

  Tier 2 — Type / range / enum / pattern / length
      Each value must match its YANG leaf's type, value range, enum set,
      regex pattern(s), and string length restrictions.

Tier 3 (mandatory / list-key / max-elements / when-clauses) and Tier 4
(application semantic cross-field rules) live elsewhere and are added in
Milestone 2.

Public API:
    validate_fill_values(intent_type, fill_values) -> (ok: bool, errors: list[str])

Note on validation completeness:
    NSP transforms the intent server-side via JavaScript before final
    deployment validation (see meta-info.json:mapping-engine="js-scripted").
    A `valid=True` result here is a STRUCTURAL LOWER BOUND — it means the
    output is consistent with the YANG schema, NOT that NSP will accept it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Tuple

try:
    from .yang_schema import LeafMeta, SchemaIndex, load_schema
except ImportError:
    # Allow loading as a top-level module (e.g. when sys.path includes data/)
    from yang_schema import LeafMeta, SchemaIndex, load_schema


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
