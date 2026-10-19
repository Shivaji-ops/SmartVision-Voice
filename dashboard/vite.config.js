import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the dashboard calls /api on its own address and Vite forwards
// it to the backend, so the browser never needs CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
