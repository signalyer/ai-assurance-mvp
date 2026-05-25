import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

// CISO Console SPA build config.
// API base URL injected via VITE_API_BASE_URL — see .env.example.
// Dev proxy forwards /api/v1/* to the local engine to avoid CORS during development.

export default defineConfig({
  plugins: [preact()],
  server: {
    port: 5175,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['preact', '@preact/signals', 'wouter-preact'],
        },
      },
    },
  },
});
