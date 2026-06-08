import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  // Fix-X14: 代码分包. D3.js (~500KB gzip 前) 和 marked/DOMPurify (~80KB)
  // 跟 React 业务代码混在一个 bundle, 首屏 > 700KB 加载慢. 拆 3 个 vendor
  // chunk 让浏览器并行下载 + 长期缓存复用 (d3/marked 很少变).
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
    // 单 chunk 上限 500KB 警告, 大于这个浏览器会拆 lazy load
    chunkSizeWarningLimit: 500,
  },
});
