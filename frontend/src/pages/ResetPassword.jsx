import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { authApi } from "../api/client";

export default function ResetPassword() {
  const { token } = useParams();
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.resetPassword(token, newPassword);
      setDone(true);
      setTimeout(() => navigate("/login"), 2000);
    } catch (err) {
      setError(err.response?.data?.detail || "Reset failed — the link may be invalid or expired.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <h1>Set a New Password</h1>

        {done ? (
          <div className="info-banner">Password reset. Redirecting to login…</div>
        ) : (
          <>
            <label>
              New Password
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                autoFocus
              />
            </label>

            {error && <div className="error-banner">{error}</div>}

            <button type="submit" disabled={loading}>
              {loading ? "Please wait…" : "Reset Password"}
            </button>
          </>
        )}

        <p className="auth-switch">
          <Link to="/login">Back to login</Link>
        </p>
      </form>
    </div>
  );
}
