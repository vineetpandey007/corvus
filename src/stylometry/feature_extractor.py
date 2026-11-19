"""
Stylometric feature extraction (forensic-grade).

Extracts multi-layered authorship features:
1. Function-word frequency profile (expanded authorship-attribution set)
2. Universal POS distribution (over all tokens, not just alpha)
3. Structural/lexical metrics (sentence length mean/std, word length,
   punctuation profile, lexical richness / TTR, casing & digit habits)
4. Cleaned text payload for character n-gram TF-IDF comparison
"""

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Dict, List

import spacy

# Expanded topic-independent function-word set (70 words)
FUNCTION_WORDS = [
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on",
    "at", "for", "with", "as", "by", "is", "are", "was", "were", "be",
    "been", "being", "this", "that", "these", "those", "it", "its", "he",
    "she", "they", "we", "you", "i", "me", "my", "our", "your", "their",
    "have", "has", "had", "do", "does", "did", "not", "no", "so", "just",
    "very", "too", "also", "only", "about", "from", "into", "out", "up",
    "all", "some", "any", "more", "most", "which", "who", "what", "when",
    "where", "because",
]

UNIVERSAL_POS_TAGS = [
    "ADJ", "ADP", "ADV", "AUX", "CCONJ", "DET", "INTJ", "NOUN", "NUM",
    "PART", "PRON", "PROPN", "PUNCT", "SCONJ", "SYM", "VERB", "X",
]

PUNCT_CHARS = (".", ",", ";", ":", "!", "?", "-")


@lru_cache(maxsize=1)
def _get_nlp():
    """Lazy-load spaCy without NER for faster startup and safe imports."""
    try:
        return spacy.load("en_core_web_sm", disable=["ner"])
    except OSError as exc:
        raise RuntimeError(
            "spaCy model not found. Run: python -m spacy download en_core_web_sm"
        ) from exc


def extract_features(text: str) -> Dict[str, Any]:
    """
    Extract a rich stylometric feature dictionary from text.
    Backward-compatible keys are preserved alongside new forensic metrics.
    """
    nlp = _get_nlp()
    doc = nlp(text)
    sentences = list(doc.sents)

    words = [t.text for t in doc if t.is_alpha]
    lower_words = [w.lower() for w in words]
    total_words = max(len(words), 1)
    total_chars = max(len(text), 1)

    sent_lengths = [
        sum(1 for t in sent if t.is_alpha) for sent in sentences
    ]
    avg_sentence_length = (
        sum(sent_lengths) / len(sent_lengths) if sent_lengths else 0.0
    )
    if len(sent_lengths) > 1:
        variance = sum((x - avg_sentence_length) ** 2 for x in sent_lengths) / len(sent_lengths)
        std_sentence_length = math.sqrt(variance)
    else:
        std_sentence_length = 0.0

    avg_word_length = sum(len(w) for w in words) / total_words if words else 0.0
    type_token_ratio = len(set(lower_words)) / total_words if words else 0.0

    punct_count = len(re.findall(r"[.,;:!?\-]", text))
    punctuation_ratio = punct_count / total_chars
    punctuation_profile = {
        ch: text.count(ch) / total_chars for ch in PUNCT_CHARS
    }

    uppercase_ratio = sum(1 for c in text if c.isupper()) / total_chars
    digit_ratio = sum(1 for c in text if c.isdigit()) / total_chars

    word_counts = Counter(lower_words)
    function_word_freq = {
        fw: word_counts.get(fw, 0) / total_words for fw in FUNCTION_WORDS
    }

    # Count POS over ALL non-space tokens so NUM, PUNCT, SYM, X are populated
    pos_tokens = [t.pos_ for t in doc if not t.is_space]
    pos_counts = Counter(pos_tokens)
    total_pos = max(len(pos_tokens), 1)
    pos_distribution = {
        pos: pos_counts.get(pos, 0) / total_pos for pos in UNIVERSAL_POS_TAGS
    }

    return {
        "avg_sentence_length": avg_sentence_length,
        "std_sentence_length": std_sentence_length,
        "avg_word_length": avg_word_length,
        "type_token_ratio": type_token_ratio,
        "punctuation_ratio": punctuation_ratio,
        "punctuation_profile": punctuation_profile,
        "uppercase_ratio": uppercase_ratio,
        "digit_ratio": digit_ratio,
        "function_word_freq": function_word_freq,
        "pos_distribution": pos_distribution,
        "char_count": len(text),
        "word_count": len(words),
        "normalized_text": re.sub(r"\s+", " ", text.strip().lower()),
    }


def flatten_features(features: Dict[str, Any]) -> List[float]:
    """
    Flatten features into a SCALE-NORMALIZED vector so scalar metrics
    (e.g., sentence length ~20) cannot drown out frequency distributions.
    """
    # Normalize scalars onto ~[0, 1] range using domain bounds
    vec = [
        min(features["avg_sentence_length"] / 40.0, 1.5),
        min(features.get("std_sentence_length", 0.0) / 20.0, 1.5),
        min(features["avg_word_length"] / 10.0, 1.5),
        features.get("type_token_ratio", 0.0),
        min(features["punctuation_ratio"] * 10.0, 1.5),
        min(features.get("uppercase_ratio", 0.0) * 5.0, 1.5),
        min(features.get("digit_ratio", 0.0) * 5.0, 1.5),
    ]
    vec.extend(features["function_word_freq"][fw] for fw in FUNCTION_WORDS)
    vec.extend(features["pos_distribution"][pos] for pos in UNIVERSAL_POS_TAGS)
    return vec