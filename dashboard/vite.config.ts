import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server forwards /v1/* to the FastAPI backend. The browser sees ONE origin
// (localhost:5173), so there is no CORS and the refresh cookie works as in production.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  build: {
    rolldownOptions: {
      output: {
        // Libraries change rarely: keep them in their own file so browsers cache it across our releases.
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/ },
            { name: 'vendor', test: /node_modules[\\/]/ },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // Public demo links (cloudflared quick tunnels) reach this server under their own host name.
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      // ws: connectors use this same address for their live link, so one link serves everything.
      '/v1': { target: 'http://127.0.0.1:8000', ws: true },
    },
  },
  // `vite preview` (the built dashboard) reuses the server settings above.
})
