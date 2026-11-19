import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { casesApi } from "../api/client";

export default function CaseList() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [title, setTitle] = useState("");
  const [legalBasis, setLegalBasis] = useState("");
  const [creating, setCreating] = useState(false);

  const navigate = useNavigate();

  async function loadCases() {
    setLoading(true);
    try {
      const resp = await casesApi.list();
      setCases(resp.data);
    } catch (err) {
      setError("Could not load cases. Is the API running?");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadCases();
  }, []);

  async function handleCreate(e) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const resp = await casesApi.create(title, legalBasis);
      navigate(`/cases/${resp.data.case_id}`);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create case.");
    } finally {
      setCreating(false);
    }
  }

  function handleLogout() {
    localStorage.removeItem("access_token");
    navigate("/login");
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Investigations</h1>
        <button className="secondary" onClick={handleLogout}>
          Log out
        </button>
      </header>

      <section className="card">
        <h2>Open a New Case</h2>
        <form onSubmit={handleCreate} className="case-form">
          <label>
            Case title
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="e.g. Operation Nightfall — Forum Alpha vendor cluster"
            />
          </label>
          <label>
            Legal basis / authorization reference
            <input
              value={legalBasis}
              onChange={(e) => setLegalBasis(e.target.value)}
              placeholder="e.g. Warrant #2026-XXXX, cyber-cell case ref"
            />
          </label>
          <button type="submit" disabled={creating}>
            {creating ? "Creating…" : "Create Case"}
          </button>
        </form>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section>
        <h2>Your Cases</h2>
        {loading ? (
          <p>Loading…</p>
        ) : cases.length === 0 ? (
          <p className="muted">No cases yet — create one above to get started.</p>
        ) : (
          <ul className="case-list">
            {cases.map((c) => (
              <li key={c.case_id}>
                <Link to={`/cases/${c.case_id}`}>{c.title}</Link>
                <span className="case-id">#{c.case_id}</span>
                {c.legal_basis && <span className="legal-basis">{c.legal_basis}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
