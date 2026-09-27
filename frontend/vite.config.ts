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
  // `vite preview` serves the built dist/ with the same /api proxy, which is
  // the static-site topology the browser gates in scripts/ui run against.
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 5000,
  },
});
