"""
Username Matcher — forensic handle correlation with leetspeak normalization,
guarded phonetic matching, and generic-handle false-positive suppression.
"""

import re
from functools import lru_cache
from typing import Any, Dict, Tuple

import jellyfish
from rapidfuzz import fuzz

from src.utils.config import load_config

_LEET_MAP = str.maketrans({
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "@": "a",
    "$": "s",
    "!": "i",
})

# High-frequency handles that commonly collide across unrelated actors
GENERIC_STEMS = frozenset({
    "admin", "administrator", "mod", "moderator", "vendor", "seller",
    "buyer", "escrow", "support", "help", "anon", "anonymous", "user",
    "guest", "member", "dark", "darknet", "shadow", "ghost", "crypto",
    "btc", "xmr", "market", "shop", "store", "official", "real", "test",
})

_COMMON_AFFIX_RE = re.compile(
    r"^(?:xx|the|real|official|mr|dr)+|(?:xx|official|real|vendor|shop|store|dark)+$"
)


@lru_cache(maxsize=1)
def _get_username_cfg() -> Dict[str, Any]:
    return load_config().get("username", {})


def _normalize(alias: str) -> str:
    """Lowercase and strip non-alphanumeric separators."""
    return re.sub(r"[^a-z0-9]", "", alias.lower())


def _extract_stem_and_digits(alias: str) -> Tuple[str, str]:
    """
    Return (de-leeted alpha stem, trailing digits) for structural comparison.
    Example: 'Sh4d0w_Br0ker_99' -> ('shadowbroker', '99')
    """
    cleaned = re.sub(r"[^a-z0-9@$!]", "", alias.lower())
    m = re.match(r"^(.*?)(\d*)$", cleaned)
    raw_stem, trailing_digits = m.group(1), m.group(2)
    de_leeted = re.sub(r"[^a-z]", "", raw_stem.translate(_LEET_MAP))
    return de_leeted, trailing_digits


def compare_usernames(alias_a: str, alias_b: str) -> Dict[str, Any]:
    """Compare two aliases and return a calibrated similarity verdict."""
    cfg = _get_username_cfg()
    threshold = cfg.get("similarity_threshold", 0.82)
    max_confidence = cfg.get("max_confidence", 0.55)

    norm_a, norm_b = _normalize(alias_a), _normalize(alias_b)
    if not norm_a or not norm_b:
        return {
            "levenshtein_score": 0.0,
            "phonetic_match": False,
            "confidence": 0.0,
            "likely_related": False,
        }

    stem_a, digits_a = _extract_stem_and_digits(alias_a)
    stem_b, digits_b = _extract_stem_and_digits(alias_b)

    # Compare both raw normalized handles and de-leeted stems + digits
    raw_ratio = fuzz.ratio(norm_a, norm_b) / 100.0
    deleet_full_a = stem_a + digits_a
    deleet_full_b = stem_b + digits_b
    deleet_ratio = fuzz.ratio(deleet_full_a, deleet_full_b) / 100.0 if (deleet_full_a and deleet_full_b) else 0.0
    lev_score = max(raw_ratio, deleet_ratio)

    # Guarded phonetic check: only on alphabetic stems >= 4 chars, and requires baseline edit proximity
    phonetic_match = False
    if len(stem_a) >= 4 and len(stem_b) >= 4:
        try:
            mp_a, mp_b = jellyfish.metaphone(stem_a), jellyfish.metaphone(stem_b)
            stem_ratio = fuzz.ratio(stem_a, stem_b) / 100.0
            # Reject digit-only mismatches on short/generic stems (e.g. admin1 vs admin9999)
            digits_conflict = bool(digits_a and digits_b and digits_a != digits_b)
            if mp_a and mp_a == mp_b and stem_ratio >= 0.70 and not digits_conflict:
                phonetic_match = True
        except Exception:
            phonetic_match = False

    # Suppress coincidental generic handle collisions (e.g. vendor1 vs vendor2)
    stripped_a = _COMMON_AFFIX_RE.sub("", stem_a) or stem_a
    stripped_b = _COMMON_AFFIX_RE.sub("", stem_b) or stem_b
    is_generic = stripped_a in GENERIC_STEMS or stripped_b in GENERIC_STEMS

    if is_generic:
        # Require near-exact full handle match and heavily cap confidence
        likely_related = lev_score >= 0.92 and (digits_a == digits_b)
        confidence = min(lev_score * 0.30, 0.25) if likely_related else 0.0
    else:
        likely_related = lev_score >= threshold or phonetic_match
        raw_confidence = max(lev_score, 0.50 if phonetic_match else 0.0)
        confidence = min(raw_confidence, max_confidence) if likely_related else 0.0

    return {
        "levenshtein_score": round(lev_score, 4),
        "phonetic_match": phonetic_match,
        "generic_handle_penalty": is_generic,
        "confidence": round(confidence, 4),
        "likely_related": likely_related,
    }