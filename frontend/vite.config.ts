import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The config runs in Node; this avoids @types/node, which would also type the app code.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  envDir: "..",
  // File events don't cross Docker Desktop bind mounts, so Compose turns on polling.
  server: process.env.CHOKIDAR_USEPOLLING
    ? { watch: { usePolling: true, interval: 500 } }
    : {},
  test: { dir: "../tests/frontend" },
});
