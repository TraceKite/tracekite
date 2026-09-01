

import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: any) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="p-8 text-[#1a1d23] bg-[#f8f9fb] min-h-screen">
          <h1 className="text-xl font-bold mb-4">Something went wrong</h1>
          <pre className="text-sm whitespace-pre-wrap text-red-600">
            {this.state.error.message}
            {"\n"}
            {this.state.error.stack}
          </pre>
          <button
            className="mt-4 px-4 py-2 bg-[#315b47] hover:bg-[#274a3a] text-white rounded"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
