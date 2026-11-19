# Ethics & Legal Use Guidelines

This document is a required read before running, demoing, or extending this
toolkit. SIH judges evaluating a cybersecurity/law-enforcement problem
statement will expect these guardrails to be part of the design, not an
afterthought.

## 1. What this tool is

An **analytics and correlation layer** over data an investigator is already
legally authorized to hold — dark-web forum posts, marketplace listings,
public blockchain transactions, and leaked/breach data obtained through
proper legal channels (court order, lawful OSINT collection, partner threat-
intel feeds, etc.).

## 2. What this tool is NOT

- It does **not** break Tor's anonymity network, perform traffic-correlation
  attacks, or deanonymize the Tor protocol itself.
- It does **not** decrypt PGP-encrypted content — it only reads *unencrypted
  metadata* such as key fingerprints that senders voluntarily publish.
- It does **not** perform unauthorized intrusion, exploitation, or access of
  any system, account, or wallet.
- It is **not** a mass-surveillance tool — it is designed for case-scoped,
  authorized investigations, not bulk deanonymization of ordinary users.

## 3. Required operating principles

1. **Legal authorization first.** Every investigation run through this tool
   should be tied to a documented legal basis (warrant, court order, or
   applicable law-enforcement authority under India's IT Act 2000 and
   Cr.P.C., or your jurisdiction's equivalent).
2. **Case-scoping.** Analysts should only ingest data relevant to an active,
   authorized case — not open-ended bulk collection.
3. **Chain of custody.** Every ingestion, correlation, and export action
   must be logged (who, what, when) so results are usable as evidence and
   auditable later. See `src/utils/logger.py` for the audit-log hook.
4. **False-positive awareness.** Stylometric and correlation matches are
   probabilistic, not proof. Every match the tool surfaces must show a
   confidence score and be treated as a *lead*, not a conclusion.
5. **No targeting of protected activity.** This tool must not be used
   against journalists, whistleblowers, activists, or researchers using Tor
   for legitimate privacy reasons. Deployment policy should explicitly
   exclude such use.
6. **Data minimization & retention limits.** Collected data should be
   purged per your organization's retention policy once a case closes.

## 4. How the Current Implementation Supports This

- **`legal_basis` field**: every case created via `POST /cases` requires
  (or should require, per your deployment policy) a legal-basis reference,
  stored alongside the case for later audit review.
- **Per-analyst case ownership**: the database enforces that one analyst
  cannot read another's case data (`Case.owner_id`), reducing the risk of
  casual or unauthorized browsing of sensitive investigations.
- **Encryption at rest**: case post text is encrypted (Fernet/AES) in the
  database, decrypted only in memory when an authorized analyst requests
  it — see `src/utils/encryption.py`.
- **Audit log**: every ingest, correlation-graph build, and wallet trace
  is appended to `data/processed/audit_log.jsonl` with a timestamp, actor,
  and action — see `src/utils/logger.py::audit_log()`.

None of this replaces an actual organizational policy, legal review, or
access-control process — it's infrastructure that supports one.

## 5. For your SIH submission

In your pitch/demo, explicitly call out:
- Which legal framework your tool assumes (e.g., IT Act 2000, CrPC search
  provisions, or your state cyber-cell's SOP)
- How the audit log / chain-of-custody feature works
- That the "confidence score" on every match is shown to prevent
  overreliance on probabilistic correlation

Judges evaluating government cybersecurity problem statements consistently
reward teams that treat governance and legal compliance as a first-class
design requirement — not just the ML/algorithm work.
