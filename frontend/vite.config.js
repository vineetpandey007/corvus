import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Relative asset paths ("./assets/..." instead of "/assets/...") are
  // required for the built app to work when loaded via Electron's
  // file:// protocol — an absolute "/assets/..." path resolves against
  // the filesystem root under file://, not the app's own directory, and
  // every asset 404s. This has no effect on `npm run dev` or normal
  // http(s)://-served deployments.
  base: "./",
  server: {
    port: 5173,
  },
});
