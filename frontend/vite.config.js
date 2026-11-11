import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// За локална разработка: npm run dev (проксира /api към backend на :8000)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.API_URL || "http://localhost:8000" },
  },
});
