import { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { authApi } from "../api/client";

const BACKEND_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const OAUTH_ERROR_MESSAGES = {
  invalid_state: "Login attempt expired or was tampered with — please try again.",
  provider_error: "Could not reach the login provider — please try again.",
  missing_token: "Sign-in did not complete — please try again.",
};

export default function Login({ mode = "login" }) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const isRegister = mode === "register";
  const oauthError = searchParams.get("oauth_error");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = isRegister
        ? await authApi.register(username, email, password)
        : await authApi.login(identifier, password);
      localStorage.setItem("access_token", resp.data.access_token);
      navigate("/cases");
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "Something went wrong. Please check your credentials and try again."
      );
    } finally {
      setLoading(false);
    }
  }

  function startOAuth(provider) {
    // Full-page redirect by design — this is a standard OAuth
    // Authorization Code flow, not an XHR call the frontend can make
    // itself (the provider's consent screen can't be shown inside an
    // API response).
    window.location.href = `${BACKEND_BASE_URL}/auth/oauth/${provider}/login`;
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <h1>{isRegister ? "Create Analyst Account" : "Analyst Login"}</h1>
        <p className="auth-subtitle">
          Dark Web Identity Correlation Toolkit — authorized use only
        </p>

        {oauthError && (
          <div className="error-banner">
            {OAUTH_ERROR_MESSAGES[oauthError] || "Sign-in failed — please try again."}
          </div>
        )}

        <div className="oauth-buttons">
          <button type="button" className="oauth-button" onClick={() => startOAuth("google")}>
            Continue with Google
          </button>
          <button type="button" className="oauth-button" onClick={() => startOAuth("github")}>
            Continue with GitHub
          </button>
        </div>
        <div className="auth-divider"><span>or</span></div>

        {isRegister ? (
          <>
            <label>
              Username
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
              />
            </label>
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
          </>
        ) : (
          <label>
            Username or Email
            <input
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
            />
          </label>
        )}

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
          />
        </label>

        {error && <div className="error-banner">{error}</div>}

        <button type="submit" disabled={loading}>
          {loading ? "Please wait…" : isRegister ? "Register" : "Log In"}
        </button>

        {!isRegister && (
          <p className="auth-links-row">
            <Link to="/forgot-password">Forgot password?</Link>
            <Link to="/otp-login">Log in with OTP instead</Link>
          </p>
        )}

        <p className="auth-switch">
          {isRegister ? (
            <>
              Already have an account? <Link to="/login">Log in</Link>
            </>
          ) : (
            <>
              Need an account? <Link to="/register">Register</Link>
            </>
          )}
        </p>
      </form>
    </div>
  );
}
