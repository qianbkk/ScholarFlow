import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

// R10.5.54 (frontend rebuild): inline root ErrorBoundary.
// 保留为 React 18 防御层 — 单次崩溃不白屏, 给用户 reset 按钮.
class RootErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('RootErrorBoundary caught:', error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            padding: 32,
            fontFamily: 'IBM Plex Sans, sans-serif',
            maxWidth: 600,
            margin: '64px auto',
            color: 'var(--sf-text)',
          }}
        >
          <h1 style={{ fontSize: 20, marginBottom: 12 }}>界面渲染出错</h1>
          <p style={{ fontSize: 14, color: 'var(--sf-muted)', marginBottom: 16 }}>
            已捕获到 React 渲染错误, 避免整页白屏.
          </p>
          <pre
            style={{
              padding: 12,
              background: 'var(--sf-surface-alt)',
              border: '1px solid var(--sf-border)',
              borderRadius: 2,
              fontSize: 12,
              overflow: 'auto',
              marginBottom: 16,
            }}
          >
            {this.state.error.message}
          </pre>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            style={{
              padding: '6px 12px',
              border: '1px solid var(--sf-border)',
              background: 'transparent',
              cursor: 'pointer',
              borderRadius: 2,
              marginRight: 8,
            }}
          >
            重置界面
          </button>
          <button
            type="button"
            onClick={() => location.reload()}
            style={{
              padding: '6px 12px',
              border: '1px solid var(--sf-border)',
              background: 'transparent',
              cursor: 'pointer',
              borderRadius: 2,
            }}
          >
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>,
);