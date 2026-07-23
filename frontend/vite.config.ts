import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    // Must run before @vitejs/plugin-react (TanStack Router docs)
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
    }),
    tailwindcss(),
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: [
        'favicon.ico',
        'icons/icon.svg',
        'icons/icon-192.png',
        'icons/icon-512.png',
        'icons/apple-touch-icon.png',
      ],
      manifest: false, // public/manifest.webmanifest を使用
      injectRegister: 'script-defer',
      workbox: {
        // ハッシュ付き静的アセットのみ precache。index.html は常にネットワークから取得。
        globPatterns: ['**/*.{js,css,ico,png,svg,woff2,webmanifest}'],
        // CopilotKit 等を含むメインバンドルが 2MB を超えるため上限を緩和
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        skipWaiting: true,
        clientsClaim: true,
        navigateFallback: null,
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api'),
            handler: 'NetworkOnly',
          },
          {
            urlPattern: ({ url }) => url.pathname === '/map.geojson',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'map-geojson',
              networkTimeoutSeconds: 10,
              expiration: {
                maxEntries: 4,
                maxAgeSeconds: 60 * 60,
              },
            },
          },
        ],
      },
      devOptions: {
        enabled: false,
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/map.geojson': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
