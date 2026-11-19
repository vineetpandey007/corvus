import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

/**
 * Lands here after a successful Google/GitHub login — the backend
 * redirects to #/oauth-callback?token=<jwt> once it has exchanged the
 * provider's code and issued our own token (see src/api/routes/oauth.py).
 * This page's only job is to pick that token up and store it exactly the
 * way the normal username/password login flow does.
 */
export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useEffect(() => {
    const token = searchParams.get("token");
    if (token) {
      localStorage.setItem("access_token", token);
      navigate("/cases", { replace: true });
    } else {
      navigate("/login?oauth_error=missing_token", { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="auth-page">
      <p className="muted">Finishing sign-in…</p>
    </div>
  );
}
