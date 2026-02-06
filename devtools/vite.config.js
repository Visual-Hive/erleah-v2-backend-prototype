import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [
    tailwindcss(),
    svelte(),
  ],
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Critical for SSE: configure the proxy to not buffer
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req, res) => {
            // Tell any intermediary (nginx, etc.) not to buffer
            res.setHeader('X-Accel-Buffering', 'no');
            res.setHeader('Cache-Control', 'no-cache, no-store');
          });
        },
      },
    },
  },
});
