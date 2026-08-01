import React from 'react'
import { Button, Result, Typography } from 'antd'

const { Paragraph, Text } = Typography

interface Props {
  children: React.ReactNode
  resetKey?: string
}

interface State {
  error: Error | null
}

class AppErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidUpdate(prevProps: Props) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Route render failed', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <Result
        status="500"
        title="页面渲染失败"
        subTitle="系统已拦截异常，没有清空当前应用外壳。请刷新或返回首页。"
        extra={[
          <Button type="primary" key="reload" onClick={() => window.location.reload()}>
            刷新页面
          </Button>,
          <Button key="home" onClick={() => { window.location.href = '/' }}>
            回到首页
          </Button>,
        ]}
      >
        <Paragraph style={{ maxWidth: 720, margin: '0 auto' }}>
          <Text type="secondary">{this.state.error.message}</Text>
        </Paragraph>
      </Result>
    )
  }
}

export default AppErrorBoundary
