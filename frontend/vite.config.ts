import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // form-render@2.5.6（已是最后一个版本，全部 release 的 peer 都是 antd 4.x||5.x）
      // 内部写死了 antd5 时代的 rc-picker / rc-field-form。antd6 把它们改名成了
      // @rc-component/picker、@rc-component/form，旧模块名在 node_modules 里已不存在，
      // Rolldown 会直接报 "failed to resolve import"。这里把两个旧名指到新包，
      // 只影响 form-render 自己的内部 import（业务代码从不直接引 rc-*）。
      'rc-picker': '@rc-component/picker',
      'rc-field-form': '@rc-component/form',
    },
  },
  server: {
    port: 18888,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
