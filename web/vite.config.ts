/// <reference types="vitest/config" />
import path from "node:path"
import { fileURLToPath } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const here = path.dirname(fileURLToPath(import.meta.url))
// The production build is committed into the Python package so that
// `pip install omnirag` ships the web app without needing Node.
const outDir = path.resolve(here, "../src/omnirag/server/static")
const apiTarget = process.env.OMNIRAG_API ?? "http://127.0.0.1:8751"

// https://vite.dev/config/
export default defineConfig({
  // FastAPI serves the files under /static and the page itself at "/".
  base: "/static/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(here, "./src") },
  },
  server: {
    port: 8752,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  preview: { port: 8753, strictPort: true },
  build: {
    outDir,
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
})
