import base64

from src.blockchain.wallet_tracer import extract_wallet_addresses_typed
from src.identity_graph.graph_builder import IdentityGraphBuilder
from src.identity_graph.networkx_backend import NetworkXBackend
from src.identity_graph.pgp_correlator import correlate as pgp_correlate
from src.identity_graph.pgp_correlator import extract_wallet_addresses
from src.identity_graph.username_matcher import compare_usernames


def _new_builder(case_id="test-case"):
    # Pass an explicit fresh backend so tests don't share state via the
    # process-wide singleton in graph_builder.get_backend().
    return IdentityGraphBuilder(case_id=case_id, backend=NetworkXBackend())


def _make_test_pgp_block(seed_byte: bytes, uid: str) -> str:
    """Build a minimal RFC 4880 v4 OpenPGP public key + User ID armor block."""
    # Tag 6 (Public-Key Packet, new format: 0xC6): version 4 + 4-byte ts + algo 1 + 32-byte material
    pk_body = b"\x04\x65\x00\x00\x00\x01" + (seed_byte * 32)
    pk_packet = bytes([0xC6, len(pk_body)]) + pk_body

    # Tag 13 (User ID Packet, new format: 0xCD)
    uid_bytes = uid.encode("utf-8")
    uid_packet = bytes([0xCD, len(uid_bytes)]) + uid_bytes

    b64 = base64.b64encode(pk_packet + uid_packet).decode("ascii")
    return (
        "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n"
        f"{b64}\n"
        "-----END PGP PUBLIC KEY BLOCK-----"
    )


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
    # Noisy-OR fusion: 1 - (1 - 0.80) * (1 - 0.98) = 0.996 -> capped at 0.99
    assert edge["confidence"] == 0.99
    assert edge["confidence"] > 0.98
    assert set(edge["types"]) == {"stylometry", "pgp_key_reuse"}
    assert edge["signal_scores"] == {"stylometry": 0.8, "pgp_key_reuse": 0.98}


def test_extract_wallet_addresses_finds_eth_and_btc():
    text = (
        "Send payment to 0x1234567890abcdef1234567890abcdef12345678 "
        "or the BTC address 1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    )
    addresses = extract_wallet_addresses(text)
    assert "0x1234567890abcdef1234567890abcdef12345678" in addresses
    assert "1BoatSLRHtKNngkdXEeobR76b53LETtpyT" in addresses


def test_multichain_address_validation_rejects_bad_checksums():
    sample = (
        "Valid ETH: 0x742d35Cc6634C0532925a3b844Bc454e4438f44e "
        "Valid BTC Taproot: bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297 "
        "Bad BTC Base58 checksum: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNaX"
    )
    found = extract_wallet_addresses_typed(sample)
    by_addr = {item["address"]: item["chain"] for item in found}

    assert by_addr["0x742d35Cc6634C0532925a3b844Bc454e4438f44e"] == "ethereum"
    assert by_addr["bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297"] == "bitcoin"
    assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNaX" not in by_addr


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

    leet_result = compare_usernames("shadowbroker99", "Sh4d0w_Br0ker_99")
    assert leet_result["likely_related"] is True


def test_username_matcher_ignores_unrelated_and_generic_handles():
    result = compare_usernames("shadowbroker99", "xX_gamerguy_Xx")
    assert result["likely_related"] is False

    generic_collision = compare_usernames("admin1", "admin9999")
    assert generic_collision["likely_related"] is False
    assert generic_collision["confidence"] == 0.0


def test_pure_python_pgp_correlator_matches_key_and_uid():
    key_a = _make_test_pgp_block(b"\x11", "kestrel <kestrel@onion.mail>")
    key_a_clone = _make_test_pgp_block(b"\x11", "kestrel_alt <kestrel@onion.mail>")
    key_b_same_uid = _make_test_pgp_block(b"\x22", "kestrel <kestrel@onion.mail>")

    same_key = pgp_correlate(f"My key:\n{key_a}", f"Verify:\n{key_a_clone}")
    assert same_key["match"] is True
    assert same_key["confidence"] == 0.98
    assert same_key["fingerprint"] is not None

    same_uid = pgp_correlate(f"Old:\n{key_a}", f"New:\n{key_b_same_uid}")
    assert same_uid["match"] is True
    assert same_uid["confidence"] == 0.80


def test_build_from_posts_creates_expected_graph_and_evidence():
    posts = [
        {
            "alias": "shadowbroker99",
            "source": "forum_alpha",
            "text": "Send funds to 0x1234567890abcdef1234567890abcdef12345678 for access.",
        },
        {
            "alias": "shadow_broker_99",
            "source": "forum_beta",
            "text": "Escrow address: 0x1234567890abcdef1234567890abcdef12345678.",
        },
    ]
    builder = _new_builder()
    builder.build_from_posts(posts, actor="pytest")
    data = builder.to_json()

    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1

    edge = data["edges"][0]
    assert set(edge["types"]) == {"wallet_reuse", "username_similarity"}
    assert "0x1234567890abcdef1234567890abcdef12345678" in edge["evidence"]["wallet_reuse"]["shared_addresses"]
    # Multi-signal Noisy-OR fusion should exceed single-signal wallet confidence (0.90)
    assert edge["confidence"] > 0.90