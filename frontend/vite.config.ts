import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The API is proxied rather than called cross-origin, so `API_BASE` is a
    // relative path and development matches the built deployment (where
    // FastAPI serves `dist/` from the same origin). A hardcoded
    // `http://localhost:8000` works only on the machine that wrote it.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    // plotly.js is ~4.8 MB unminified and dwarfs everything else. Splitting it
    // out keeps the app chunk small enough to re-download on every deploy
    // while the chart engine stays in cache.
    rollupOptions: {
      output: {
        manualChunks: (id) =>
          (id.includes('plotly.js') || id.includes('react-plotly.js'))
            ? 'plotly'
            : undefined,
      },
    },
    chunkSizeWarningLimit: 5000,
  },
});
