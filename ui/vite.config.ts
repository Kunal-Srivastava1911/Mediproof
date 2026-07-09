import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to the FastAPI backend. In dev, VITE_API_BASE defaults to the local
// API; in the Docker demo it is set to the published API origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: { environment: "node" },
});
