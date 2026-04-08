"""
YANG schema parsing and indexing for NSP service intent validation.

Loads Nokia NSP service-mgmt YANG modules from `data/yang/<intent_type>/`,
walks the schema tree (resolving `import`, `uses grouping`, and `typedef`
chains via pyang), and emits a flat `SchemaIndex` of leaf metadata keyed by
positional dot-path.

The index supports both **canonical YANG path** lookup and **suffix-match**
lookup, because the project's `fill_values` protocol uses shortened paths
that strip intermediate wrapper containers (e.g., `sdp[0].sdp-id` rather
than the canonical `epipe.sdp-details.sdp[0].sdp-id`).

Public API:
    load_schema(intent_type: str) -> SchemaIndex
    SchemaIndex.has_path(dot_path: str) -> bool
    SchemaIndex.lookup(dot_path: str) -> Optional[LeafMeta]
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Set

from pyang import context, repository


YANG_DIR = os.path.join(os.path.dirname(__file__), "yang")

# Pyang ships standard IETF YANG modules (ietf-inet-types, ietf-yang-types,
# etc.) under <venv>/share/yang/modules/. Adding this directory to the
# pyang search path lets typedef chains like `inet:ipv4-address-no-zone`
# resolve to their base YANG types.
_PYANG_STD_DIRS = [
    os.path.join(sys.prefix, "share", "yang", "modules", "ietf"),
    os.path.join(sys.prefix, "share", "yang", "modules", "iana"),
    os.path.join(sys.prefix, "share", "yang", "modules", "ieee"),
]
_PYANG_STD_DIRS = [d for d in _PYANG_STD_DIRS if os.path.isdir(d)]


# ---------------------------------------------------------------------------
# NSP intent ENVELOPE fields (defined by NSP, not by per-intent YANG bundles)
# ---------------------------------------------------------------------------
#
# Every NSP intent JSON wraps the per-intent body inside a common envelope:
#
#   {
#     "nsp-service-intent:intent": [
#       {
#         "service-name": "...",         <- envelope (service intents only)
#         "intent-type": "epipe",        <- envelope
#         "intent-type-version": "2",    <- envelope
#         "olc-state": "deployed",       <- envelope
#         "template-name": "...",        <- envelope
#         "intent-specific-data": {
#           "epipe:epipe": { ... body fields modeled by epipe.yang ... }
#         }
#       }
#     ]
#   }
#
# The envelope fields are NOT defined in any of the per-intent YANG modules
# we have. They live in NSP's higher-level model. We hand-encode them here
# so the validator can recognize them as legitimate paths in fill_values.
#
# Tunnel is special: it puts `source-ne-id` and `sdp-id` at the envelope
# level, not inside `tunnel:tunnel`. This is verified at tunnel.yang:19-40
# where those leaves are commented out.

_OLC_STATE_ENUM = [
    "saved", "planned", "deployed", "deployed-modified",
    "removed", "deleted", "open",
    "planned-failed", "deployed-modified-failed", "pull-from-network-saved",
]


def _envelope_meta(name: str, **kwargs) -> "LeafMeta":
    """Helper: build an envelope LeafMeta with a synthetic path."""
    return LeafMeta(path=f"@envelope.{name}", base_type=kwargs.pop("base_type", "string"), **kwargs)


def _envelope_fields(intent_type: str) -> Dict[str, "LeafMeta"]:
    """Return the envelope-level field set for a given intent type."""
    common = {
        "intent-type":         _envelope_meta("intent-type"),
        "intent-type-version": _envelope_meta("intent-type-version"),
        "olc-state":           _envelope_meta("olc-state", base_type="enumeration", enum_values=_OLC_STATE_ENUM),
        "template-name":       _envelope_meta("template-name"),
    }
    if intent_type == "tunnel":
        # Tunnel envelope: no service-name; mandatory source-ne-id / sdp-id.
        return {
            **common,
            "source-ne-id": _envelope_meta("source-ne-id", mandatory=True),
            "sdp-id":       _envelope_meta("sdp-id",       mandatory=True),
        }
    # All service intents (epipe, vprn, vpls, ies, etree, evpn-*, cpipe, ...)
    return {
        **common,
        "service-name": _envelope_meta("service-name", length_expr="1..64"),
    }

# Regex to normalize concrete list indices (`[0]`, `[1]`, ...) to wildcard `[*]`
# so that `site-a.endpoint[0].port-id` matches the canonical `endpoint[*]`.
_INDEX_RE = re.compile(r"\[\d+\]")

# Regex to strip Nokia "wrapper" containers like `site-details.` / `sdp-details.`
# / `interface-details.` from a canonical YANG path. The user's `fill_values`
# convention drops these intermediate containers (e.g. `site[0].device-id`
# instead of `site-details.site[0].device-id`).
_WRAPPER_RE = re.compile(r"\.[\w-]+-details\.")


@dataclass
class LeafMeta:
    """Metadata extracted from a single YANG leaf or leaf-list."""

    path: str                                       # canonical YANG path with [*] for list entries
    base_type: str                                  # resolved base type after typedef chase
    range_expr: Optional[str] = None                # e.g. "1..2147483647"
    length_expr: Optional[str] = None               # e.g. "1..64"
    pattern_list: List[str] = field(default_factory=list)
    enum_values: Optional[List[str]] = None
    default: Optional[str] = None
    mandatory: bool = False
    description: str = ""
    is_leaf_list: bool = False
    union_types: Optional[List["LeafMeta"]] = None  # for union types, one entry per member


@dataclass
class ListMeta:
    """Metadata for a YANG list (the container of list entries)."""

    path: str                                       # path ends in [*]
    keys: List[str]
    max_elements: Optional[int] = None
    min_elements: Optional[int] = None


@dataclass
class SchemaIndex:
    """A flat index of all leaves in an intent's YANG schema."""

    intent_type: str
    leaves: Dict[str, LeafMeta] = field(default_factory=dict)   # canonical path -> LeafMeta
    lists: Dict[str, ListMeta] = field(default_factory=dict)    # canonical path -> ListMeta
    suffix_index: Dict[str, List[LeafMeta]] = field(default_factory=dict)  # any suffix -> matches

    def has_path(self, dot_path: str) -> bool:
        """Check whether dot_path matches any leaf in the schema (suffix-aware)."""
        norm = _normalize(dot_path)
        return norm in self.suffix_index

    def lookup(self, dot_path: str) -> Optional[LeafMeta]:
        """Return the LeafMeta for dot_path (first match if ambiguous)."""
        norm = _normalize(dot_path)
        matches = self.suffix_index.get(norm)
        return matches[0] if matches else None

    def lookup_all(self, dot_path: str) -> List[LeafMeta]:
        """Return all LeafMeta matches for an ambiguous suffix lookup."""
        norm = _normalize(dot_path)
        return list(self.suffix_index.get(norm, []))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize(path: str) -> str:
    """Replace concrete list indices with the wildcard `[*]` placeholder."""
    return _INDEX_RE.sub("[*]", path)


def _suffixes(path: str):
    """Yield all `.`-delimited suffixes of a dot-path, longest first.

    Example: `a.b[*].c.d` -> `a.b[*].c.d`, `b[*].c.d`, `c.d`, `d`.
    """
    parts = path.split(".")
    for i in range(len(parts)):
        yield ".".join(parts[i:])


def _resolve_base_type(type_stmt):
    """Walk a typedef chain to its terminating type statement (or None)."""
    seen = set()
    while type_stmt is not None and id(type_stmt) not in seen:
        seen.add(id(type_stmt))
        td = getattr(type_stmt, "i_typedef", None)
        if td is None:
            return type_stmt
        sub = td.search_one("type")
        if sub is None:
            return type_stmt
        type_stmt = sub
    return type_stmt


def _collect_restrictions(type_stmt, meta: LeafMeta) -> None:
    """Walk type stmt + typedef chain, accumulating restrictions onto meta."""
    if type_stmt is None:
        return

    # Inline restrictions on this type statement
    range_stmt = type_stmt.search_one("range")
    if range_stmt is not None and meta.range_expr is None:
        meta.range_expr = range_stmt.arg

    length_stmt = type_stmt.search_one("length")
    if length_stmt is not None and meta.length_expr is None:
        meta.length_expr = length_stmt.arg

    for p in type_stmt.search("pattern"):
        if p.arg not in meta.pattern_list:
            meta.pattern_list.append(p.arg)

    enum_stmts = type_stmt.search("enum")
    if enum_stmts and meta.enum_values is None:
        meta.enum_values = [e.arg for e in enum_stmts]

    # Union members
    if type_stmt.arg == "union":
        members: List[LeafMeta] = []
        for sub in type_stmt.search("type"):
            mem = LeafMeta(path=meta.path, base_type=_basename(sub))
            _collect_restrictions(sub, mem)
            members.append(mem)
        meta.union_types = members

    # Recurse into the typedef chain
    td = getattr(type_stmt, "i_typedef", None)
    if td is not None:
        td_type = td.search_one("type")
        if td_type is not None:
            _collect_restrictions(td_type, meta)


def _basename(type_stmt) -> str:
    """Return the base type name after typedef resolution."""
    base = _resolve_base_type(type_stmt)
    return base.arg if base is not None else "string"


def _make_leaf_meta(stmt, path: str) -> LeafMeta:
    """Build a LeafMeta from a YANG `leaf` or `leaf-list` statement."""
    type_stmt = stmt.search_one("type")
    base_type = _basename(type_stmt) if type_stmt is not None else "string"

    meta = LeafMeta(
        path=path,
        base_type=base_type,
        is_leaf_list=(stmt.keyword == "leaf-list"),
    )

    desc = stmt.search_one("description")
    if desc is not None:
        meta.description = desc.arg or ""

    deflt = stmt.search_one("default")
    if deflt is not None:
        meta.default = deflt.arg

    mand = stmt.search_one("mandatory")
    if mand is not None and mand.arg == "true":
        meta.mandatory = True

    if type_stmt is not None:
        _collect_restrictions(type_stmt, meta)

    return meta


def _walk(node, path: str, leaves: Dict[str, LeafMeta], lists: Dict[str, ListMeta]) -> None:
    """Recursively descend a pyang schema tree, populating leaves and lists."""
    children = getattr(node, "i_children", None) or []
    for child in children:
        kw = child.keyword
        name = child.arg

        if kw == "container":
            child_path = f"{path}.{name}" if path else name
            _walk(child, child_path, leaves, lists)

        elif kw == "list":
            child_path = f"{path}.{name}[*]" if path else f"{name}[*]"
            keys_stmt = child.search_one("key")
            keys = keys_stmt.arg.split() if keys_stmt is not None else []
            max_el = child.search_one("max-elements")
            min_el = child.search_one("min-elements")
            lists[child_path] = ListMeta(
                path=child_path,
                keys=keys,
                max_elements=int(max_el.arg) if max_el is not None and str(max_el.arg).isdigit() else None,
                min_elements=int(min_el.arg) if min_el is not None and str(min_el.arg).isdigit() else None,
            )
            _walk(child, child_path, leaves, lists)

        elif kw in ("leaf", "leaf-list"):
            leaf_path = f"{path}.{name}" if path else name
            leaves[leaf_path] = _make_leaf_meta(child, leaf_path)

        elif kw in ("choice", "case"):
            # choice/case are transparent — descend
            _walk(child, path, leaves, lists)

        # Skip rpc, action, notification, augment, etc.


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def load_schema(intent_type: str) -> SchemaIndex:
    """Load and index the YANG schema for a given service intent type.

    Looks for `data/yang/<intent_type>/<intent_type>.yang` as the main module
    and uses pyang to resolve imports/uses/typedefs against the same directory.
    Result is cached in-process via `lru_cache`.
    """
    yang_dir = os.path.join(YANG_DIR, intent_type)
    if not os.path.isdir(yang_dir):
        raise FileNotFoundError(f"YANG dir not found: {yang_dir}")

    main_yang = os.path.join(yang_dir, f"{intent_type}.yang")
    if not os.path.exists(main_yang):
        raise FileNotFoundError(f"Main YANG file not found: {main_yang}")

    # Build a colon-separated search path: the intent's own dir first, then
    # the IETF / IANA standard module dirs that ship with pyang.
    search_path = ":".join([yang_dir] + _PYANG_STD_DIRS)
    repo = repository.FileRepository(search_path, use_env=False)
    ctx = context.Context(repo)

    with open(main_yang) as f:
        text = f.read()
    mod = ctx.add_module(main_yang, text)
    if mod is None:
        raise RuntimeError(f"pyang failed to parse {main_yang}")

    ctx.validate()
    # Note: pyang may emit non-fatal warnings (e.g. KEY_HAS_DEFAULT for Nokia
    # YANG modules) which we ignore. Real parse failures would have left mod=None.

    leaves: Dict[str, LeafMeta] = {}
    lists: Dict[str, ListMeta] = {}

    for child in mod.i_children or []:
        if child.keyword == "container":
            _walk(child, child.arg, leaves, lists)

    # Inject NSP envelope fields (service-name, intent-type, etc.) — these
    # are NOT in the per-intent YANG modules but are part of the user's
    # fill_values protocol because they live in the outer intent envelope.
    envelope = _envelope_fields(intent_type)
    for env_name, env_meta in envelope.items():
        # Use the bare envelope name as the canonical path so it survives
        # both direct lookup and suffix-index lookup.
        leaves[env_name] = env_meta

    # Build suffix index for shorthand path matching.
    # We index BOTH the canonical path and a "wrapper-stripped" variant where
    # all `*-details` intermediate containers are removed, then take all
    # `.`-delimited suffixes of each. This is what lets the project's existing
    # fill_values protocol — `site[0].interface[0].sap.port-id` — match the
    # canonical `vprn.site-details.site[*].interface-details.interface[*].sap.port-id`.
    suffix_index: Dict[str, List[LeafMeta]] = {}
    for canonical_path, meta in leaves.items():
        variants = {canonical_path}
        # Strip all wrapper containers (handles multiple in one pass thanks to non-overlap).
        stripped = _WRAPPER_RE.sub(".", canonical_path)
        if stripped != canonical_path:
            variants.add(stripped)
        for variant in variants:
            for suf in _suffixes(variant):
                bucket = suffix_index.setdefault(suf, [])
                if meta not in bucket:
                    bucket.append(meta)

    return SchemaIndex(
        intent_type=intent_type,
        leaves=leaves,
        lists=lists,
        suffix_index=suffix_index,
    )


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for it in ("epipe", "tunnel", "vprn"):
        idx = load_schema(it)
        print(f"\n=== {it} ===")
        print(f"  leaves: {len(idx.leaves)}")
        print(f"  lists:  {len(idx.lists)}")
        print(f"  suffix_index entries: {len(idx.suffix_index)}")
        print(f"  sample canonical paths:")
        for p in sorted(idx.leaves.keys())[:8]:
            m = idx.leaves[p]
            extras = []
            if m.range_expr: extras.append(f"range={m.range_expr}")
            if m.enum_values: extras.append(f"enum={m.enum_values[:3]}")
            if m.mandatory: extras.append("mandatory")
            print(f"    {p}  ({m.base_type}{', '+', '.join(extras) if extras else ''})")
