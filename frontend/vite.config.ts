import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Ishlab chiqishda: /api so'rovlari backend'ga (8000) yo'naltiriladi.
// Tayyor (build) holatda frontend backend'ning o'zidan beriladi.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", emptyOutDir: true },
});
