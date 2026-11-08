import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'node:fs'
import path from 'node:path'

function apiTarget() {
  if (process.env.API_TARGET) return process.env.API_TARGET
  try {
    const p = fs.readFileSync(path.resolve('data/.port'), 'utf8').trim()
    if (p) return `http://127.0.0.1:${p}`
  } catch {}
  return 'http://127.0.0.1:8390'
}

export default defineConfig({
  base: './',
  plugins: [vue()],
  server: {
    port: 5175,
    proxy: { '/api': { target: apiTarget(), changeOrigin: true } }
  },
  build: { chunkSizeWarningLimit: 1500 }
})