import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authApi } from "../api/client";

export default function OtpLogin() {
  const [step, setStep] = useState("request"); // "request" | "verify"
  const [identifier, setIdentifier] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleRequest(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = await authApi.otpRequest(identifier);
      setMessage(resp.data.message);
      setStep("verify");
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = await authApi.otpVerify(identifier, code);
      localStorage.setItem("access_token", resp.data.access_token);
      navigate("/cases");
    } catch (err) {
      setError(err.response?.data?.detail || "Invalid or expired code.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={step === "request" ? handleRequest : handleVerify}>
        <h1>Log In with OTP</h1>

        {step === "request" ? (
          <>
            <p className="auth-subtitle">Enter your username or email to receive a one-time code.</p>
            <label>
              Username or Email
              <input
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                required
                autoFocus
              />
            </label>
          </>
        ) : (
          <>
            {message && <div className="info-banner">{message}</div>}
            <label>
              6-Digit Code
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                minLength={6}
                maxLength={6}
                pattern="[0-9]{6}"
                autoFocus
              />
            </label>
          </>
        )}

        {error && <div className="error-banner">{error}</div>}

        <button type="submit" disabled={loading}>
          {loading ? "Please wait…" : step === "request" ? "Send Code" : "Verify & Log In"}
        </button>

        <p className="auth-switch">
          <Link to="/login">Back to password login</Link>
        </p>
      </form>
    </div>
  );
}
