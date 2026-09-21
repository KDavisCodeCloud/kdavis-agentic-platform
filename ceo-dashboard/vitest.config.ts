import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Minimal test setup -- no test runner existed in this app before the
// Email Campaign HITL queue build (2026-09-21). Scoped to what that
// feature needs to verify: the shared backend-client logic (degradation,
// auth headers) and role gating on its proxy routes.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
