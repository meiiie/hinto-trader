import { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
    children: ReactNode;
    fallback?: ReactNode;
    onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

/**
 * Error Boundary Component - Catches JavaScript errors in child components
 *
 * Usage:
 * <ErrorBoundary fallback={<div>Something went wrong</div>}>
 *   <ComponentThatMayFail />
 * </ErrorBoundary>
 */
export class ErrorBoundary extends Component<Props, State> {
    public state: State = {
        hasError: false,
        error: null,
    };

    public static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    public componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
        console.error('ErrorBoundary caught an error:', error, errorInfo);
        this.props.onError?.(error, errorInfo);
    }

    public render(): ReactNode {
        if (this.state.hasError) {
            if (this.props.fallback) {
                return this.props.fallback;
            }

            return (
                <div style={{
                    padding: '20px',
                    backgroundColor: '#1E2329',
                    border: '1px solid #F6465D',
                    borderRadius: '8px',
                    color: '#EAECEF',
                    fontFamily: 'system-ui, -apple-system, sans-serif',
                }}>
                    <h3 style={{ color: '#F6465D', margin: '0 0 12px 0' }}>
                        ⚠️ Something went wrong
                    </h3>
                    <p style={{ color: '#848E9C', margin: '0 0 12px 0', fontSize: '14px' }}>
                        {this.state.error?.message || 'An unexpected error occurred'}
                    </p>
                    <button
                        onClick={() => this.setState({ hasError: false, error: null })}
                        style={{
                            padding: '8px 16px',
                            backgroundColor: '#2B3139',
                            border: '1px solid #5E6673',
                            borderRadius: '6px',
                            color: '#EAECEF',
                            cursor: 'pointer',
                            fontSize: '14px',
                        }}
                    >
                        Try Again
                    </button>
                </div>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
