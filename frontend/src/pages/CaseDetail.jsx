import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { casesApi, reportsApi, nlpApi } from "../api/client";
import GraphView from "../components/GraphView";

const EMPTY_POST = { alias: "", source: "", text: "" };

function formatApiError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const loc = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        return loc ? `${loc}: ${item.msg}` : item.msg || JSON.stringify(item);
      })
      .join(" | ");
  }
  return typeof detail === "object" ? JSON.stringify(detail) : String(detail);
}

function renderEvidenceSummary(edge) {
  const ev = edge.evidence || {};
  const parts = [];

  if (ev.wallet_reuse?.shared_addresses?.length) {
    parts.push(`Wallet: ${ev.wallet_reuse.shared_addresses.join(", ")}`);
  }
  if (ev.pgp_key_reuse?.shared_fingerprints?.length) {
    parts.push(`PGP FP: ${ev.pgp_key_reuse.shared_fingerprints.join(", ")}`);
  } else if (ev.pgp_key_reuse?.shared_user_ids?.length) {
    parts.push(`PGP UID: ${ev.pgp_key_reuse.shared_user_ids.join(", ")}`);
  }
  if (ev.stylometry?.breakdown) {
    const b = ev.stylometry.breakdown;
    parts.push(
      `Style (char ${(b.char_ngram_similarity * 100).toFixed(0)}%, fw ${(
        b.function_word_similarity * 100
      ).toFixed(0)}%, pos ${(b.pos_similarity * 100).toFixed(0)}%)`
    );
  }
  if (ev.username_similarity) {
    parts.push(
      `Handle (lev ${(ev.username_similarity.levenshtein_score * 100).toFixed(0)}%${
        ev.username_similarity.phonetic_match ? ", phonetic" : ""
      })`
    );
  }

  return parts.length > 0 ? parts.join(" • ") : "Probabilistic signal match";
}

export default function CaseDetail() {
  const { caseId } = useParams();
  const [graph, setGraph] = useState(null);
  const [posts, setPosts] = useState([]);
  const [report, setReport] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [exporting, setExporting] = useState(null); // "txt" | "pdf" | null
  const [draftPosts, setDraftPosts] = useState([{ ...EMPTY_POST }]);
  const [loading, setLoading] = useState(true);
  const [ingesting, setIngesting] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("graph");
  const [queryInput, setQueryInput] = useState("");
  const [queryHistory, setQueryHistory] = useState([]);
  const [queryLoading, setQueryLoading] = useState(false);
  const [suggestions, setSuggestions] = useState(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [auditStatus, setAuditStatus] = useState(null);
  const [verifyingAudit, setVerifyingAudit] = useState(false);

  async function loadCaseData(signal = { cancelled: false }) {
    setLoading(true);
    try {
      const [graphResp, postsResp] = await Promise.all([
        casesApi.getGraph(caseId),
        casesApi.getPosts(caseId),
      ]);
      if (!signal.cancelled) {
        setGraph(graphResp.data);
        setPosts(postsResp.data);
      }
    } catch (err) {
      if (!signal.cancelled) {
        setError(formatApiError(err, "Could not load case data."));
      }
    } finally {
      if (!signal.cancelled) {
        setLoading(false);
      }
    }
  }

  // Reset all case-scoped state when switching between cases
  useEffect(() => {
    const signal = { cancelled: false };
    setGraph(null);
    setPosts([]);
    setReport(null);
    setSuggestions(null);
    setQueryHistory([]);
    setDraftPosts([{ ...EMPTY_POST }]);
    setAuditStatus(null);
    setError("");
    loadCaseData(signal);
    return () => {
      signal.cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  useEffect(() => {
    let cancelled = false;
    if (activeTab === "report" && !report && !reportLoading) {
      setReportLoading(true);
      reportsApi
        .getReport(caseId)
        .then((resp) => {
          if (!cancelled) setReport(resp.data);
        })
        .catch((err) => {
          if (!cancelled) setError(formatApiError(err, "Could not load report."));
        })
        .finally(() => {
          if (!cancelled) setReportLoading(false);
        });
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, caseId]);

  useEffect(() => {
    let cancelled = false;
    if (activeTab === "insights" && !suggestions && !suggestionsLoading) {
      setSuggestionsLoading(true);
      nlpApi
        .getSuggestions(caseId)
        .then((resp) => {
          if (!cancelled) setSuggestions(resp.data.suggestions);
        })
        .catch((err) => {
          if (!cancelled) setError(formatApiError(err, "Could not load suggestions."));
        })
        .finally(() => {
          if (!cancelled) setSuggestionsLoading(false);
        });
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, caseId]);

  async function handleVerifyAudit() {
    setVerifyingAudit(true);
    setError("");
    try {
      if (typeof casesApi.verifyAudit === "function") {
        const resp = await casesApi.verifyAudit(caseId);
        setAuditStatus(resp.data);
      } else {
        const apiBase =
          window.corvusDesktop?.backendUrl ||
          import.meta.env.VITE_API_URL ||
          "http://localhost:8000";
        const token = localStorage.getItem("token") || localStorage.getItem("access_token");
        const resp = await fetch(`${apiBase}/cases/${caseId}/audit-verify`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!resp.ok) throw new Error("Audit verification failed");
        setAuditStatus(await resp.json());
      }
    } catch (err) {
      setError(formatApiError(err, "Could not verify audit log integrity."));
    } finally {
      setVerifyingAudit(false);
    }
  }

  async function runQuery(text) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setQueryLoading(true);
    setError("");
    try {
      const resp = await nlpApi.query(caseId, trimmed);
      setQueryHistory((prev) => [
        ...prev,
        {
          query: trimmed,
          answer: resp.data.answer,
          followUps: resp.data.follow_up_questions || [],
        },
      ]);
      setQueryInput("");
    } catch (err) {
      setError(formatApiError(err, "Query failed."));
    } finally {
      setQueryLoading(false);
    }
  }

  async function handleExport(format) {
    setExporting(format);
    setError("");
    try {
      if (format === "txt") await reportsApi.downloadTxt(caseId);
      else await reportsApi.downloadPdf(caseId);
    } catch (err) {
      setError(formatApiError(err, `Export to ${format.toUpperCase()} failed.`));
    } finally {
      setExporting(null);
    }
  }

  function updateDraft(index, field, value) {
    setDraftPosts((prev) =>
      prev.map((p, i) => (i === index ? { ...p, [field]: value } : p))
    );
  }

  function addDraftRow() {
    setDraftPosts((prev) => [...prev, { ...EMPTY_POST }]);
  }

  function removeDraftRow(index) {
    setDraftPosts((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleIngest(e) {
    e.preventDefault();
    setError("");
    const validPosts = draftPosts
      .map((p) => ({
        alias: p.alias.trim(),
        source: p.source.trim(),
        text: p.text.trim(),
      }))
      .filter((p) => p.alias && p.text);

    if (validPosts.length === 0) {
      setError("Enter at least one post with a non-empty alias and text.");
      return;
    }

    setIngesting(true);
    try {
      await casesApi.ingest(caseId, validPosts);
      setDraftPosts([{ ...EMPTY_POST }]);
      setReport(null);
      setSuggestions(null);
      setAuditStatus(null);
      await loadCaseData();
      setActiveTab("graph");
    } catch (err) {
      setError(formatApiError(err, "Ingest failed."));
    } finally {
      setIngesting(false);
    }
  }

  const edges = graph?.edges || [];

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <Link to="/cases" className="back-link">
            ← All cases
          </Link>
          <h1>Case #{caseId}</h1>
        </div>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          {auditStatus && (
            <span
              className="muted"
              style={{
                fontSize: "0.85rem",
                color: auditStatus.valid ? "#4ade80" : "#f87171",
              }}
            >
              {auditStatus.valid
                ? `Audit Chain Verified (${auditStatus.entries} entries)`
                : `Audit Chain Broken at line ${auditStatus.broken_at_line}`}
            </span>
          )}
          <button
            type="button"
            className="secondary"
            onClick={handleVerifyAudit}
            disabled={verifyingAudit}
          >
            {verifyingAudit ? "Verifying…" : "Verify Audit Chain"}
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="tabs">
        <button
          className={activeTab === "graph" ? "tab active" : "tab"}
          onClick={() => setActiveTab("graph")}
        >
          Identity Graph
        </button>
        <button
          className={activeTab === "ingest" ? "tab active" : "tab"}
          onClick={() => setActiveTab("ingest")}
        >
          Ingest Posts
        </button>
        <button
          className={activeTab === "posts" ? "tab active" : "tab"}
          onClick={() => setActiveTab("posts")}
        >
          Case Posts ({posts.length})
        </button>
        <button
          className={activeTab === "report" ? "tab active" : "tab"}
          onClick={() => setActiveTab("report")}
        >
          Report
        </button>
        <button
          className={activeTab === "insights" ? "tab active" : "tab"}
          onClick={() => setActiveTab("insights")}
        >
          Query & Insights
        </button>
      </div>

      {loading ? (
        <p>Loading…</p>
      ) : (
        <>
          {activeTab === "graph" && (
            <section className="card">
              <GraphView graph={graph} />

              {edges.length > 0 && (
                <div style={{ marginTop: "1.5rem" }}>
                  <h3>Forensic Correlation Breakdown</h3>
                  <table className="posts-table">
                    <thead>
                      <tr>
                        <th>Alias Pair</th>
                        <th>Signals</th>
                        <th>Confidence</th>
                        <th>Underlying Evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {edges.map((edge, idx) => (
                        <tr key={`${edge.source}-${edge.target}-${idx}`}>
                          <td>
                            <strong>{edge.source}</strong> ↔ <strong>{edge.target}</strong>
                          </td>
                          <td>{(edge.types || []).join(", ")}</td>
                          <td>{Math.round((edge.confidence || 0) * 100)}%</td>
                          <td className="post-text-cell">{renderEvidenceSummary(edge)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {activeTab === "ingest" && (
            <section className="card">
              <h2>Add Posts to This Case</h2>
              <p className="muted">
                Add lawfully collected posts/aliases to run through the
                correlation pipeline (stylometry, PGP key reuse, wallet
                reuse, username similarity). Text is encrypted at rest and
                hashed (SHA-256) on ingestion.
              </p>
              <form onSubmit={handleIngest}>
                {draftPosts.map((post, idx) => (
                  <div className="post-draft-row" key={idx}>
                    <input
                      placeholder="Alias / handle"
                      value={post.alias}
                      onChange={(e) => updateDraft(idx, "alias", e.target.value)}
                      required
                    />
                    <input
                      placeholder="Source (forum name, URL, etc.)"
                      value={post.source}
                      onChange={(e) => updateDraft(idx, "source", e.target.value)}
                    />
                    <textarea
                      placeholder="Post text"
                      value={post.text}
                      onChange={(e) => updateDraft(idx, "text", e.target.value)}
                      rows={3}
                      required
                    />
                    {draftPosts.length > 1 && (
                      <button
                        type="button"
                        className="remove-row"
                        onClick={() => removeDraftRow(idx)}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                ))}
                <div className="ingest-actions">
                  <button type="button" className="secondary" onClick={addDraftRow}>
                    + Add another post
                  </button>
                  <button type="submit" disabled={ingesting}>
                    {ingesting ? "Ingesting…" : "Ingest & Correlate"}
                  </button>
                </div>
              </form>
            </section>
          )}

          {activeTab === "posts" && (
            <section className="card">
              <h2>Stored Evidence Posts (decrypted for review)</h2>
              {posts.length === 0 ? (
                <p className="muted">No posts ingested yet.</p>
              ) : (
                <table className="posts-table">
                  <thead>
                    <tr>
                      <th>Alias</th>
                      <th>Source</th>
                      <th>Text</th>
                      <th>SHA-256 Digest</th>
                      <th>Ingested</th>
                    </tr>
                  </thead>
                  <tbody>
                    {posts.map((p, idx) => (
                      <tr key={p.id || idx}>
                        <td>{p.alias}</td>
                        <td>{p.source}</td>
                        <td className="post-text-cell">{p.text}</td>
                        <td
                          title={p.evidence_sha256 || ""}
                          style={{ fontFamily: "monospace", fontSize: "0.8rem" }}
                        >
                          {p.evidence_sha256 ? `${p.evidence_sha256.slice(0, 16)}…` : "—"}
                        </td>
                        <td>{new Date(p.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}

          {activeTab === "report" && (
            <section className="card">
              <div className="report-header">
                <h2>Case Report</h2>
                <div className="report-export-buttons">
                  <button
                    className="secondary"
                    onClick={() => handleExport("txt")}
                    disabled={exporting !== null || !report}
                  >
                    {exporting === "txt" ? "Exporting…" : "Export TXT"}
                  </button>
                  <button
                    className="secondary"
                    onClick={() => handleExport("pdf")}
                    disabled={exporting !== null || !report}
                  >
                    {exporting === "pdf" ? "Exporting…" : "Export PDF"}
                  </button>
                </div>
              </div>

              {reportLoading ? (
                <p className="muted">Generating report…</p>
              ) : !report ? (
                <p className="muted">No report data yet.</p>
              ) : (
                <>
                  <div className="report-summary">
                    <div className="report-stat">
                      <span className="report-stat-value">{report.summary.total_aliases}</span>
                      <span className="report-stat-label">Aliases</span>
                    </div>
                    <div className="report-stat">
                      <span className="report-stat-value">{report.summary.total_correlations}</span>
                      <span className="report-stat-label">Correlations</span>
                    </div>
                    <div className="report-stat">
                      <span className="report-stat-value">{report.summary.isolated_alias_count}</span>
                      <span className="report-stat-label">Uncorrelated</span>
                    </div>
                  </div>

                  <h3>Key Findings</h3>
                  {report.findings.length === 0 ? (
                    <p className="muted">No correlations were found among the ingested aliases.</p>
                  ) : (
                    <ul className="report-findings-list">
                      {report.findings.map((f, idx) => (
                        <li key={idx}>
                          <strong>{f.confidence_pct}%</strong> — {f.text}
                        </li>
                      ))}
                    </ul>
                  )}

                  {report.isolated_aliases.length > 0 && (
                    <>
                      <h3>Uncorrelated Aliases</h3>
                      <ul className="report-findings-list">
                        {report.isolated_aliases.map((a) => (
                          <li key={a}>{a} — no correlation found with any other alias</li>
                        ))}
                      </ul>
                    </>
                  )}

                  <p className="report-disclaimer">
                    Every finding above is a probabilistic correlation, not a
                    confirmed identity match. Treat each as a lead requiring
                    further investigation.
                  </p>
                </>
              )}
            </section>
          )}

          {activeTab === "insights" && (
            <section className="card">
              <h2>Ask About This Case</h2>
              <p className="muted">
                Answers come directly from this case's graph and post data —
                not an open-ended AI chat. Try the suggested questions below,
                or type your own using the same kind of phrasing.
              </p>

              <form
                className="query-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  runQuery(queryInput);
                }}
              >
                <input
                  value={queryInput}
                  onChange={(e) => setQueryInput(e.target.value)}
                  placeholder='e.g. "Summarize this case" or "Who is shadowbroker99 linked to?"'
                />
                <button type="submit" disabled={queryLoading || !queryInput.trim()}>
                  {queryLoading ? "Asking…" : "Ask"}
                </button>
              </form>

              {queryHistory.length === 0 ? (
                <p className="muted">No questions asked yet.</p>
              ) : (
                <div className="query-history">
                  {queryHistory.map((item, idx) => (
                    <div className="query-entry" key={idx}>
                      <div className="query-entry-question">Q: {item.query}</div>
                      <div className="query-entry-answer">{item.answer}</div>
                      {item.followUps.length > 0 && (
                        <div className="follow-up-chips">
                          {item.followUps.map((fq) => (
                            <button
                              key={fq}
                              type="button"
                              className="follow-up-chip"
                              onClick={() => runQuery(fq)}
                              disabled={queryLoading}
                            >
                              {fq}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <h2 className="insights-suggestions-heading">Suggested Next Steps</h2>
              {suggestionsLoading ? (
                <p className="muted">Analyzing case…</p>
              ) : !suggestions || suggestions.length === 0 ? (
                <p className="muted">No suggestions for this case yet.</p>
              ) : (
                <ul className="suggestions-list">
                  {suggestions.map((s, idx) => (
                    <li key={idx}>
                      <div className="suggestion-text">{s.suggestion}</div>
                      <div className="suggestion-reason">{s.reason}</div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}