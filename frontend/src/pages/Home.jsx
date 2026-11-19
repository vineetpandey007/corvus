import { Link } from "react-router-dom";

const SIGNALS = [
  {
    name: "Stylometry",
    color: "#4C6EF5",
    desc: "Writing-style fingerprinting — sentence length, punctuation habits, function-word frequency — flags aliases likely written by the same person.",
  },
  {
    name: "PGP Key Reuse",
    color: "#F03E3E",
    desc: "Detects when two aliases have published the same PGP public key fingerprint, a common OPSEC mistake linking otherwise separate identities.",
  },
  {
    name: "Wallet Reuse",
    color: "#F59F00",
    desc: "Correlates cryptocurrency addresses shared across posts, plus public on-chain analysis for Ethereum and Bitcoin.",
  },
  {
    name: "Username Similarity",
    color: "#12B886",
    desc: "Levenshtein + phonetic matching between handles — deliberately capped at low confidence, since coincidental similarity is common.",
  },
];

export default function Home() {
  return (
    <div className="home-page">
      <header className="home-hero">
        <div className="home-hero-inner">
          <span className="home-eyebrow">SIH 2026 &middot; Problem Statement #151</span>
          <h1>Dark Web Identity Correlation Toolkit</h1>
          <p className="home-subtitle">
            An investigative analytics platform that helps threat-intel analysts
            correlate pseudonymous dark-web identities — using stylometry, PGP
            key reuse, wallet reuse, and username similarity — with every match
            scored as a confidence percentage, never a certainty.
          </p>
          <div className="home-cta-row">
            <Link to="/register" className="home-cta-primary">Get Started</Link>
            <Link to="/login" className="home-cta-secondary">Log In</Link>
          </div>
        </div>
      </header>

      <section className="home-section">
        <h2>How Correlation Works</h2>
        <p className="home-section-sub">
          Four independent signals, each contributing a confidence-scored edge
          to a case's identity graph. No single signal is ever treated as proof.
        </p>
        <div className="home-signal-grid">
          {SIGNALS.map((s) => (
            <div className="home-signal-card" key={s.name}>
              <span className="home-signal-dot" style={{ backgroundColor: s.color }} />
              <h3>{s.name}</h3>
              <p>{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="home-section home-notice">
        <h2>Authorized Use Only</h2>
        <p>
          This tool does not break Tor, decrypt anything, or gain unauthorized
          access to any system. It is a correlation layer over data an
          investigator is already legally authorized to collect. Every case
          requires a recorded legal basis, every action is chain-of-custody
          logged, and case data is encrypted at rest.
        </p>
      </section>

      <footer className="home-footer">
        <Link to="/register">Create an analyst account &rarr;</Link>
      </footer>
    </div>
  );
}
