import { Component, type ReactNode, type ErrorInfo } from 'react';

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

// R10.5 Fix-X1: 顶层 ErrorBoundary — 防 React 渲染错误导致"白屏"
// 之前: 任何 marked/DOMPurify/d3 抛错 → 整个 App unmount → 整页空白, 用户只能刷新.
// 现在: 错误被边界捕获, 渲染降级 UI + "重置" 按钮, 不再让用户面对白屏.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 上报到 console (开发期) + 可扩展到 Sentry
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] caught render error:', error, info);
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return (
        <div
          className="h-screen flex items-center justify-center p-6 bg-rose-50"
          role="alert"
          data-testid="app-error-boundary"
        >
          <div className="max-w-md text-center">
            <div className="text-5xl mb-3" role="img" aria-label="error">⚠️</div>
            <h1 className="text-lg font-semibold text-rose-900 mb-2">
              界面渲染出错
            </h1>
            <p className="text-sm text-rose-700 mb-3">
              已捕获到 React 渲染错误, 避免整页白屏.
            </p>
            <pre className="text-left text-[10px] bg-white border border-rose-200 rounded p-2 mb-4 max-h-32 overflow-auto font-mono text-rose-800">
              {this.state.error.message}
            </pre>
            <div className="flex gap-2 justify-center">
              <button
                type="button"
                onClick={this.reset}
                className="px-4 py-1.5 bg-rose-600 text-white text-sm rounded-md hover:bg-rose-700 transition"
                data-testid="app-error-reset"
              >
                重置界面
              </button>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="px-4 py-1.5 bg-white border border-rose-300 text-rose-700 text-sm rounded-md hover:bg-rose-100 transition"
              >
                刷新页面
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
