import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App.jsx";
import "./styles.css";

// HashRouter (URL fragments, e.g. index.html#/cases) rather than
// BrowserRouter: required for the app to work correctly when loaded via
// Electron's file:// protocol, where there's no server to resolve an
// arbitrary path like /cases/abc123 on a hard refresh or deep link.
// Also works fine for a normal http(s) deployment, so this isn't a
// desktop-only tradeoff.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>
);
