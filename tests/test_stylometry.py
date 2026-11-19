from src.stylometry.feature_extractor import extract_features, flatten_features
from src.stylometry.author_matcher import compare_authors

SAMPLE_TEXT_A = (
    "I have been selling access for a while now and honestly, I think the "
    "market has gotten a lot more competitive lately, which is why I always "
    "double check before I ship anything to a buyer, because trust is "
    "everything in this business."
)

SAMPLE_TEXT_B = (
    "Been doing this for a while now and honestly, I think the market has "
    "gotten a lot more competitive lately, which is why I always double "
    "check before I ship anything to a buyer, because trust is everything "
    "in this business."
)

UNRELATED_TEXT = (
    "yo does anyone know a good vpn rn, mine keeps dropping and its "
    "annoying af, need something reliable for streaming mostly tbh not "
    "really into the technical stuff just want it to work lol honestly, "
    "kinda tired of googling this every single week and getting no answers."
)


def test_extract_features_returns_expected_keys():
    features = extract_features(SAMPLE_TEXT_A)
    assert "avg_sentence_length" in features
    assert "avg_word_length" in features
    assert "punctuation_ratio" in features
    assert "function_word_freq" in features
    assert "pos_distribution" in features


def test_flatten_features_consistent_length():
    vec_a = flatten_features(extract_features(SAMPLE_TEXT_A))
    vec_b = flatten_features(extract_features(SAMPLE_TEXT_B))
    assert len(vec_a) == len(vec_b)


def test_compare_authors_similar_texts_score_higher_than_unrelated():
    similar_result = compare_authors(SAMPLE_TEXT_A, SAMPLE_TEXT_B)
    unrelated_result = compare_authors(SAMPLE_TEXT_A, UNRELATED_TEXT)

    assert similar_result["similarity_score"] is not None
    assert unrelated_result["similarity_score"] is not None
    assert similar_result["similarity_score"] >= unrelated_result["similarity_score"]


def test_compare_authors_warns_on_short_text():
    result = compare_authors("too short", "also too short")
    assert result["similarity_score"] is None
    assert "warning" in result
