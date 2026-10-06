import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// `npm run dev` serves the page with reloading and forwards the API to the application on 127.0.0.1:8000
export default defineConfig({
  plugins: [svelte()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 900, rollupOptions: { input: { main: 'index.html', activity: 'activity.html' } } },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000', '/events': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' },
  },
});
