import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import './index.css';

// R10.5 Fix-X1: 顶层 ErrorBoundary 包 App, 任何组件 render 抛错时被捕获,
// 渲染降级 UI 而非 React 18 默认 unmount 整个根 → 白屏.
// 学术工具长时间使用 + LLM 输出大报告 + d3 模拟图, 渲染层容易出边界 case.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
