"""
Wallet Tracer & Multi-Chain Address Extractor (Production-Hardened).

- Migrated to Etherscan API V2 (https://api.etherscan.io/v2/api) with chainid support.
- Scoped requests_cache.CachedSession (no global monkey-patching).
- Separates strong co-spend clustering (with CoinJoin guard) from weak counterparties.
- Validates BTC Base58Check / Bech32(m), ETH hex, Monero, and Tron addresses.
"""

import hashlib
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import requests
import requests_cache
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.utils.config import get_app_data_dir
from src.utils.logger import audit_log, get_logger

logger = get_logger()

ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"
BLOCKSTREAM_BASE_URL = "https://blockstream.info/api"

EVM_CHAIN_IDS = {
    "ethereum": 1,
    "arbitrum": 42161,
    "polygon": 137,
    "optimism": 10,
    "base": 8453,
}

# Scoped cache session — never monkey-patches global `requests`
_SESSION = requests_cache.CachedSession(
    cache_name=str(get_app_data_dir() / "blockchain_cache"),
    expire_after=3600,
    allowable_codes=(200,),
)

# --- Address Extraction & Validation ---

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_MAP = {ch: idx for idx, ch in enumerate(_BASE58_ALPHABET)}

_ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_BTC_BECH32_RE = re.compile(r"\b(bc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38,59})\b", re.IGNORECASE)
_BTC_LEGACY_RE = re.compile(r"\b([13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_XMR_RE = re.compile(r"\b([48][0-9AB][1-9A-HJ-NP-Za-km-z]{93})\b")
_TRX_RE = re.compile(r"\b(T[1-9A-HJ-NP-Za-km-z]{33})\b")


def _verify_base58check(address: str) -> bool:
    """Verify Base58Check 4-byte double-SHA256 checksum (BTC legacy & Tron)."""
    try:
        num = 0
        for ch in address:
            num = num * 58 + _BASE58_MAP[ch]
        raw = num.to_bytes(25, "big")
    except (KeyError, OverflowError):
        return False
    payload, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return checksum == expected


def extract_wallet_addresses_typed(text: str) -> List[Dict[str, str]]:
    """
    Extract and validate cryptocurrency addresses with chain labels.
    Supports BTC (Legacy, SegWit, Taproot), EVM (0x), Monero (XMR), and Tron (TRX).
    """
    found: List[Tuple[str, str]] = []

    for addr in _ETH_RE.findall(text):
        # Ignore trivial burn/placeholder zero-address
        if addr.lower() != "0x" + "0" * 40:
            found.append((addr, "ethereum"))

    for addr in _BTC_BECH32_RE.findall(text):
        # Enforce BIP-173/350 no mixed-case rule
        if addr == addr.lower() or addr == addr.upper():
            found.append((addr.lower(), "bitcoin"))

    for addr in _BTC_LEGACY_RE.findall(text):
        if _verify_base58check(addr):
            found.append((addr, "bitcoin"))

    for addr in _XMR_RE.findall(text):
        found.append((addr, "monero"))

    for addr in _TRX_RE.findall(text):
        if _verify_base58check(addr):
            found.append((addr, "tron"))

    seen = set()
    results = []
    for addr, chain in found:
        key = (addr.lower() if chain in ("ethereum", "bitcoin") else addr, chain)
        if key not in seen:
            seen.add(key)
            results.append({"address": addr, "chain": chain})
    return results


def extract_wallet_addresses(text: str) -> List[str]:
    """Backward-compatible wrapper returning deduplicated validated address strings."""
    return [item["address"] for item in extract_wallet_addresses_typed(text)]


# --- HTTP Retry Policy ---

def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)
def _get(url: str, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    resp = _SESSION.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp


# --- Public Tracing API ---

def trace_wallet(address: str, chain: str = "ethereum", actor: str = "system") -> Dict[str, Any]:
    """Trace an address's public on-chain activity with forensic separation of signals."""
    chain = chain.lower()
    if chain not in EVM_CHAIN_IDS and chain != "bitcoin":
        raise ValueError(
            f"Unsupported chain: '{chain}'. Supported: bitcoin, {', '.join(EVM_CHAIN_IDS)}."
        )

    try:
        if chain == "bitcoin":
            result = _trace_bitcoin(address)
        else:
            result = _trace_evm(address, chain)
    except (requests.RequestException, ValueError, RuntimeError) as e:
        logger.error(f"Wallet trace failed for {address} on {chain}: {e}")
        result = {
            "address": address,
            "chain": chain,
            "linked_addresses": [],
            "same_entity_candidates": [],
            "counterparties": [],
            "cluster_confidence": 0.0,
            "notes": f"Trace failed after retries ({type(e).__name__}: {e})",
            "error": True,
        }

    audit_log(
        action="wallet_trace",
        actor=actor,
        details={
            "address": address,
            "chain": chain,
            "linked_count": len(result["linked_addresses"]),
            "same_entity_count": len(result.get("same_entity_candidates", [])),
        },
    )
    return result


def _trace_evm(address: str, chain: str = "ethereum") -> Dict[str, Any]:
    if not _ETH_RE.fullmatch(address):
        raise ValueError(f"Invalid EVM address format: {address}")

    api_key = os.environ.get("BLOCKEXPLORER_API_KEY")
    if not api_key:
        logger.warning("BLOCKEXPLORER_API_KEY not set — returning placeholder result.")
        return {
            "address": address,
            "chain": chain,
            "linked_addresses": [],
            "same_entity_candidates": [],
            "counterparties": [],
            "cluster_confidence": 0.0,
            "notes": "No API key configured — set BLOCKEXPLORER_API_KEY in .env for live Etherscan V2 tracing.",
        }

    chain_id = EVM_CHAIN_IDS[chain]
    normal_txs = _fetch_etherscan_v2_list(address, chain_id, "txlist", api_key)
    erc20_txs = _fetch_etherscan_v2_list(address, chain_id, "tokentx", api_key)

    bidirectional, counterparties = _analyze_evm_txs(normal_txs + erc20_txs, address)

    # Bidirectional interaction is stronger than one-way payment, but EVM has no UTXO co-spend,
    # so cap single-hop heuristic confidence conservatively below UTXO co-spend.
    if bidirectional:
        confidence = min(0.55 + 0.05 * len(bidirectional), 0.75)
    elif counterparties:
        confidence = 0.35
    else:
        confidence = 0.0

    linked = sorted(set(bidirectional) | set(counterparties))
    return {
        "address": address,
        "chain": chain,
        "chain_id": chain_id,
        "linked_addresses": linked,
        "same_entity_candidates": bidirectional,
        "counterparties": counterparties,
        "cluster_confidence": round(confidence, 4),
        "notes": (
            f"Analyzed {len(normal_txs)} native + {len(erc20_txs)} ERC-20 txs on {chain}: "
            f"{len(bidirectional)} bidirectional counterparties, {len(counterparties)} one-way."
        ),
    }


def _fetch_etherscan_v2_list(
    address: str, chain_id: int, action: str, api_key: str, offset: int = 200
) -> List[Dict[str, Any]]:
    params = {
        "chainid": chain_id,
        "module": "account",
        "action": action,
        "address": address,
        "page": 1,
        "offset": offset,
        "sort": "desc",
        "apikey": api_key,
    }
    resp = _get(ETHERSCAN_V2_URL, params=params)
    data = resp.json()
    result = data.get("result")

    if data.get("status") == "0":
        msg = str(data.get("message", ""))
        res_str = str(result or "")
        if "No transactions found" in msg or "No transactions found" in res_str:
            return []
        raise RuntimeError(f"Etherscan V2 error ({action}): {msg} — {res_str}")

    return result if isinstance(result, list) else []


def _analyze_evm_txs(
    tx_list: List[Dict[str, Any]], self_address: str
) -> Tuple[List[str], List[str]]:
    self_lower = self_address.lower()
    sent_to: Counter = Counter()
    received_from: Counter = Counter()

    for tx in tx_list:
        if not isinstance(tx, dict):
            continue
        frm = (tx.get("from") or "").lower()
        to = (tx.get("to") or "").lower()
        if frm == self_lower and to and to != self_lower:
            sent_to[to] += 1
        elif to == self_lower and frm and frm != self_lower:
            received_from[frm] += 1

    bidirectional = sorted(set(sent_to.keys()) & set(received_from.keys()))
    one_way = sorted((set(sent_to.keys()) | set(received_from.keys())) - set(bidirectional))
    return bidirectional, one_way


def _trace_bitcoin(address: str) -> Dict[str, Any]:
    if not (_BTC_BECH32_RE.fullmatch(address) or (
        _BTC_LEGACY_RE.fullmatch(address) and _verify_base58check(address)
    )):
        raise ValueError(f"Invalid Bitcoin address: {address}")

    resp = _get(f"{BLOCKSTREAM_BASE_URL}/address/{address}/txs")
    txs = resp.json()
    if not isinstance(txs, list):
        raise RuntimeError("Unexpected Blockstream response format")

    co_spends, counterparties, coinjoin_skipped = _extract_btc_signals(txs, address)

    if co_spends:
        # Common-input-ownership heuristic (excluding suspected CoinJoins)
        confidence = min(0.75 + 0.03 * len(co_spends), 0.90)
    elif counterparties:
        confidence = 0.30
    else:
        confidence = 0.0

    linked = sorted(set(co_spends) | set(counterparties))
    return {
        "address": address,
        "chain": "bitcoin",
        "linked_addresses": linked,
        "same_entity_candidates": co_spends,
        "counterparties": counterparties,
        "coinjoin_txs_skipped": coinjoin_skipped,
        "cluster_confidence": round(confidence, 4),
        "notes": (
            f"Found {len(co_spends)} co-spend input addresses and {len(counterparties)} "
            f"counterparties across {len(txs)} txs ({coinjoin_skipped} suspected CoinJoin txs skipped)."
        ),
    }


def _is_probable_coinjoin(tx: Dict[str, Any]) -> bool:
    """Heuristic CoinJoin detector: >=5 distinct input addresses + >=3 equal-value outputs."""
    vin_addrs = {
        vin.get("prevout", {}).get("scriptpubkey_address")
        for vin in tx.get("vin", [])
        if vin.get("prevout") and vin["prevout"].get("scriptpubkey_address")
    }
    if len(vin_addrs) < 5:
        return False
    out_values = Counter(vout.get("value") for vout in tx.get("vout", []) if vout.get("value"))
    return any(count >= 3 for count in out_values.values())


def _extract_btc_signals(
    tx_list: List[Dict[str, Any]], self_address: str
) -> Tuple[List[str], List[str], int]:
    co_spends = set()
    counterparties = set()
    coinjoin_skipped = 0

    for tx in tx_list:
        vin_addrs = {
            vin.get("prevout", {}).get("scriptpubkey_address")
            for vin in tx.get("vin", [])
            if vin.get("prevout") and vin["prevout"].get("scriptpubkey_address")
        }
        if self_address not in vin_addrs:
            continue

        if _is_probable_coinjoin(tx):
            coinjoin_skipped += 1
            continue

        co_spends.update(a for a in vin_addrs if a != self_address)

        vout_addrs = {
            vout.get("scriptpubkey_address")
            for vout in tx.get("vout", [])
            if vout.get("scriptpubkey_address")
        }
        counterparties.update(a for a in vout_addrs if a != self_address)

    counterparties -= co_spends
    return sorted(co_spends), sorted(counterparties), coinjoin_skipped