"""
Author Matcher — probabilistic stylometric authorship attribution.

Combines four independently scaled signals so no single raw scalar
(such as sentence length) can dominate the similarity score:
  1. Character 3-4-gram TF-IDF cosine similarity (weight: 0.50)
  2. Function-word distribution cosine similarity (weight: 0.25)
  3. Universal POS distribution cosine similarity (weight: 0.15)
  4. Standardized structural profile RBF similarity (weight: 0.10)
"""

from functools import lru_cache
from typing import Any, Dict, Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.stylometry.feature_extractor import (
    FUNCTION_WORDS,
    PUNCT_CHARS,
    UNIVERSAL_POS_TAGS,
    extract_features,
)
from src.utils.config import load_config


@lru_cache(maxsize=1)
def _get_stylometry_cfg() -> Dict[str, Any]:
    return load_config().get("stylometry", {})


def _safe_cosine(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    val = float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
    return max(0.0, min(1.0, val))


def _char_ngram_similarity(text_a: str, text_b: str) -> float:
    if not text_a.strip() or not text_b.strip():
        return 0.0
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 4),
        sublinear_tf=True,
        min_df=1,
    )
    matrix = vectorizer.fit_transform([text_a, text_b])
    return float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])


def _structural_similarity(feat_a: Dict[str, Any], feat_b: Dict[str, Any]) -> float:
    """
    RBF (Gaussian) kernel over domain-standardized structural features.
    Prevents positive-quadrant cosine inflation.
    """
    # (key, scale) pairs representing typical inter-author std dev
    specs = [
        ("avg_sentence_length", 10.0),
        ("std_sentence_length", 6.0),
        ("avg_word_length", 1.2),
        ("type_token_ratio", 0.15),
        ("punctuation_ratio", 0.02),
        ("uppercase_ratio", 0.05),
        ("digit_ratio", 0.03),
    ]
    sq_dist = 0.0
    for key, scale in specs:
        diff = (feat_a.get(key, 0.0) - feat_b.get(key, 0.0)) / scale
        sq_dist += diff * diff
    mean_sq_dist = sq_dist / len(specs)
    return float(np.exp(-0.5 * mean_sq_dist))


def compare_profiles(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
    threshold: Optional[float] = None,
    min_len: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Compare two pre-extracted stylometric profiles (O(1) NLP overhead).
    Preferred for batch / graph correlation.
    """
    cfg = _get_stylometry_cfg()
    threshold = threshold if threshold is not None else cfg.get("similarity_threshold", 0.75)
    min_len = min_len if min_len is not None else cfg.get("min_text_length_chars", 200)

    if feat_a.get("char_count", 0) < min_len or feat_b.get("char_count", 0) < min_len:
        return {
            "similarity_score": None,
            "likely_same_author": False,
            "threshold_used": threshold,
            "warning": (
                f"One or both texts are shorter than the configured minimum "
                f"({min_len} chars) — result would be unreliable."
            ),
        }

    char_sim = _char_ngram_similarity(
        feat_a.get("normalized_text", ""),
        feat_b.get("normalized_text", ""),
    )

    fw_a = np.array([feat_a["function_word_freq"][w] for w in FUNCTION_WORDS])
    fw_b = np.array([feat_b["function_word_freq"][w] for w in FUNCTION_WORDS])
    fw_sim = _safe_cosine(fw_a, fw_b)

    pos_a = np.array([feat_a["pos_distribution"][p] for p in UNIVERSAL_POS_TAGS])
    pos_b = np.array([feat_b["pos_distribution"][p] for p in UNIVERSAL_POS_TAGS])
    pos_sim = _safe_cosine(pos_a, pos_b)

    struct_sim = _structural_similarity(feat_a, feat_b)

    # Punctuation profile tie-breaker blended into structural score
    p_a = np.array([feat_a.get("punctuation_profile", {}).get(c, 0.0) for c in PUNCT_CHARS])
    p_b = np.array([feat_b.get("punctuation_profile", {}).get(c, 0.0) for c in PUNCT_CHARS])
    punct_sim = _safe_cosine(p_a, p_b)
    struct_combined = 0.7 * struct_sim + 0.3 * punct_sim

    composite = (
        0.50 * char_sim
        + 0.25 * fw_sim
        + 0.15 * pos_sim
        + 0.10 * struct_combined
    )
    score = round(max(0.0, min(1.0, composite)), 4)

    return {
        "similarity_score": score,
        "likely_same_author": score >= threshold,
        "threshold_used": threshold,
        "breakdown": {
            "char_ngram_similarity": round(char_sim, 4),
            "function_word_similarity": round(fw_sim, 4),
            "pos_similarity": round(pos_sim, 4),
            "structural_similarity": round(struct_combined, 4),
        },
    }


def compare_authors(text_a: str, text_b: str) -> Dict[str, Any]:
    """Compare two raw text samples and return a scored stylometric verdict."""
    cfg = _get_stylometry_cfg()
    threshold = cfg.get("similarity_threshold", 0.75)
    min_len = cfg.get("min_text_length_chars", 200)

    if len(text_a) < min_len or len(text_b) < min_len:
        return {
            "similarity_score": None,
            "likely_same_author": False,
            "threshold_used": threshold,
            "warning": (
                f"One or both texts are shorter than the configured minimum "
                f"({min_len} chars) — result would be unreliable."
            ),
        }

    return compare_profiles(
        extract_features(text_a),
        extract_features(text_b),
        threshold=threshold,
        min_len=min_len,
    )