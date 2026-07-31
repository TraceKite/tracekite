"""Flag-guarded call sites: the condition an edge runs under.

`if flags.isEnabled("checkout-v2"): call(...)` is a real dependency with
a rider — it only fires when the flag is on. The guard is read from the
AST, never from lexical proximity: a call is conditional exactly when
its line sits inside the CONSEQUENCE block of an `if` whose condition
contains a recognised flag check naming a string-literal flag.

Deliberately not marked: negated checks, else branches, non-literal flag
names, and every language without an AST parser here. A missing
condition is only missing metadata; a wrong condition claims the edge is
off when it is live — the expensive direction.
"""

import re

from adduce.parsers.tree_sitter.core.models import LanguageType
from adduce.parsers.tree_sitter.core.parser import TreeSitterParser

# Method names that read a feature flag across the common SDKs:
# LaunchDarkly (variation/boolVariation), Unleash (isEnabled), OpenFeature
# (getBooleanValue), Flagsmith/home-grown (isFeatureEnabled/featureEnabled).
_FLAG_CALLS = re.compile(
    r"\b(variation|boolVariation|bool_variation|isEnabled|is_enabled|"
    r"getBooleanValue|get_boolean_value|isFeatureEnabled|"
    r"is_feature_enabled|featureEnabled|feature_enabled)\b")
_NEGATION = re.compile(r"(^|[^\w])(!|not\s)")
_STRING = re.compile(r"""["']([A-Za-z0-9_.:\-]+)["']""")

_AST_LANGUAGES = {
    "python": LanguageType.PYTHON,
    "javascript": LanguageType.JAVASCRIPT,
    "typescript": LanguageType.TYPESCRIPT,
    "java": LanguageType.JAVA,
    "go": LanguageType.GO,
}

_parser: TreeSitterParser | None = None


def _core() -> TreeSitterParser:
    global _parser
    if _parser is None:
        _parser = TreeSitterParser()
    return _parser


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def guarded_ranges(content: str, language: str) -> list[dict]:
    """Consequence line ranges of positive flag checks, from the AST."""
    lang = _AST_LANGUAGES.get(language)
    if lang is None:
        return []
    root = _core().parse_ast_root(content, lang)
    if root is None:
        return []
    ranges = []
    for node in _walk(root):
        if node.type != "if_statement":
            continue
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        if condition is None or consequence is None:
            continue
        text = condition.text.decode("utf8", errors="replace")
        if not _FLAG_CALLS.search(text) or _NEGATION.search(text):
            continue
        literal = _STRING.search(text)
        if not literal:
            continue                      # a flag we cannot name marks nothing
        ranges.append({"flag": literal.group(1),
                       "start": consequence.start_point[0] + 1,
                       "end": consequence.end_point[0] + 1})
    return ranges


def annotate_flag_guards(sites: list, content: str, language: str) -> list:
    """Stamp each call site inside a guarded block with its condition.

    Cheap by construction: the AST is parsed only when the file mentions a
    flag API at all, so the common file costs one regex scan.
    """
    if not sites or not _FLAG_CALLS.search(content):
        return sites
    ranges = guarded_ranges(content, language)
    if not ranges:
        return sites
    for site in sites:
        for guard in ranges:
            if guard["start"] <= site.line <= guard["end"]:
                site.attrs["flag"] = guard["flag"]
                break
    return sites
