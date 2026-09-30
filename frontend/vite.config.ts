import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In sviluppo il backend gira su :8000 (uvicorn) e Vite fa da proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
      '/files': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
