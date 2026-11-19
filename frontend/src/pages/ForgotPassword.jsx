import { useState } from "react";
import { Link } from "react-router-dom";
import { authApi } from "../api/client";

export default function ForgotPassword() {
  const [identifier, setIdentifier] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      const resp = await authApi.forgotPassword(identifier);
      setMessage(resp.data.message);
    } catch {
      setMessage("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <h1>Reset Password</h1>
        <p className="auth-subtitle">
          Enter your username or email — if an account exists, a reset link will be sent.
        </p>

        <label>
          Username or Email
          <input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            required
            autoFocus
          />
        </label>

        {message && <div className="info-banner">{message}</div>}

        <button type="submit" disabled={loading}>
          {loading ? "Please wait…" : "Send Reset Link"}
        </button>

        <p className="auth-switch">
          <Link to="/login">Back to login</Link>
        </p>
      </form>
    </div>
  );
}
