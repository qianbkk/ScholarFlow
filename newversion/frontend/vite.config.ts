import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 6173,
    proxy: {
      // v3 backend lives on port 9000, prefix /api/v3
      '/api': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-d3': ['d3'],
          'vendor-markdown': ['marked', 'dompurify'],
        },
      },
    },
    chunkSizeWarningLimit: 500,
  },
});
