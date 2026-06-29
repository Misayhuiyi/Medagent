import { Component, type ReactNode, type ErrorInfo } from 'react'

interface Props { children: ReactNode }
interface State { error: Error | null; info: string }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: '' }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info: info.componentStack || '' })
    console.error('ErrorBoundary caught:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 16, color: '#ff3b30', fontSize: 13 }}>
          <strong>渲染错误：</strong>
          <pre style={{ whiteSpace: 'pre-wrap', marginTop: 8, fontSize: 12, color: '#666' }}>
            {this.state.error.message}
          </pre>
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', color: '#999' }}>组件栈</summary>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 10, color: '#999', marginTop: 4 }}>
              {this.state.info}
            </pre>
          </details>
        </div>
      )
    }
    return this.props.children
  }
}
