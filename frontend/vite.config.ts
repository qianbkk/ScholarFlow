import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // R10.5 Fix-P0-vite-proxy: 后端 R10.5 Fix-P2-4-Audit-diff 引入了 /api/v1/* 前缀
      // 路由, 旧 rewrite `path.replace(/^\/api/, '')` 会把 /api/v1/* 剥成 /v1/*,
      // 但后端没有 /v1/* 路由 (注册的是 /api/v1/* 和 /search/* alias), 全部 404.
      // 修复: 不做 rewrite, 路径原样转发, 后端 /api/v1/* 直接命中.
      // R10.5.20: dev 端口 8000 经常被占, 实际本地后端用 8766, proxy 跟实际端口对齐.
      '/api': {
        target: 'http://127.0.0.1:8766',
        changeOrigin: true,
        // rewrite 已移除 — 后端路由前缀包含 /api/v1, 不能再剥 /api.
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
