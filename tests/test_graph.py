from src.identity_graph.graph_builder import IdentityGraphBuilder
from src.identity_graph.networkx_backend import NetworkXBackend
from src.identity_graph.pgp_correlator import extract_wallet_addresses
from src.identity_graph.username_matcher import compare_usernames


def _new_builder(case_id="test-case"):
    # Pass an explicit fresh backend so tests don't share state via the
    # process-wide singleton in graph_builder.get_backend().
    return IdentityGraphBuilder(case_id=case_id, backend=NetworkXBackend())


def test_add_alias_and_correlation():
    builder = _new_builder()
    builder.add_alias("alias_a")
    builder.add_alias("alias_b")
    builder.add_correlation("alias_a", "alias_b", "stylometry", 0.9)

    data = builder.to_json()
    edge = next(e for e in data["edges"] if {e["source"], e["target"]} == {"alias_a", "alias_b"})
    assert edge["confidence"] == 0.9
    assert "stylometry" in edge["types"]


def test_correlation_strengthens_on_second_signal():
    builder = _new_builder()
    builder.add_alias("alias_a")
    builder.add_alias("alias_b")
    builder.add_correlation("alias_a", "alias_b", "stylometry", 0.8)
    builder.add_correlation("alias_a", "alias_b", "pgp_key_reuse", 0.98)

    data = builder.to_json()
    edge = next(e for e in data["edges"] if {e["source"], e["target"]} == {"alias_a", "alias_b"})
    assert edge["confidence"] == 0.98
    assert set(edge["types"]) == {"stylometry", "pgp_key_reuse"}


def test_extract_wallet_addresses_finds_eth_and_btc():
    text = (
        "Send payment to 0x1234567890abcdef1234567890abcdef12345678 "
        "or the BTC address 1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    )
    addresses = extract_wallet_addresses(text)
    assert "0x1234567890abcdef1234567890abcdef12345678" in addresses
    assert "1BoatSLRHtKNngkdXEeobR76b53LETtpyT" in addresses


def test_to_json_shape():
    builder = _new_builder()
    builder.add_alias("alias_a")
    builder.add_alias("alias_b")
    builder.add_correlation("alias_a", "alias_b", "stylometry", 0.9)

    data = builder.to_json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1


def test_username_matcher_flags_close_variants():
    result = compare_usernames("shadowbroker99", "shadow_broker_99")
    assert result["likely_related"] is True
    assert result["confidence"] > 0.0


def test_username_matcher_ignores_unrelated_handles():
    result = compare_usernames("shadowbroker99", "xX_gamerguy_Xx")
    assert result["likely_related"] is False


def test_build_from_posts_creates_expected_graph():
    posts = [
        {"alias": "shadowbroker99", "text": "a" * 300},
        {"alias": "shadow_broker_99", "text": "b" * 300},
    ]
    builder = _new_builder()
    builder.build_from_posts(posts, actor="pytest")
    data = builder.to_json()
    assert len(data["nodes"]) == 2
