// ESLint 10 flat config —— 2026-10-11 补。
//
// 背景：这个仓库此前**没有任何 eslint 配置**，而 package.json 里的
// `eslint . --ext ts,tsx` 用了 ESLint 9 起已移除的 --ext 标志
// ⇒ lint 从来没有真正跑起来过。这里补上能跑的配置。
//
// lint 不在 build 门禁里（门禁是 `tsc --noEmit && vite build`），
// 所以存量告警按 warn 报出来、不拦提交。
import js from '@eslint/js'
import globals from 'globals'
import tseslint from '@typescript-eslint/eslint-plugin'
import tsparser from '@typescript-eslint/parser'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['dist/**', 'node_modules/**', '*.min.js'] },
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsparser,
      parserOptions: { ecmaVersion: 2022, sourceType: 'module', ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.es2021 },
    },
    plugins: { '@typescript-eslint': tseslint, 'react-hooks': reactHooks },
    rules: {
      ...tseslint.configs.recommended.rules,

      // TS 自己就查未定义；重复报只会刷屏
      'no-undef': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { args: 'none', ignoreRestSiblings: true }],

      // 基础 no-redeclare 不认 TS 的「类型/值」双命名空间。
      // 例：src/pages/equipment/FiveSAudit.tsx 里 `interface FiveSAudit` +
      // `const FiveSAudit: React.FC`，这是合法 TS（声明合并），不是重复定义。
      'no-redeclare': 'off',

      // JSX 文本里的全角空格（U+3000）是中文排版的有意用法，不是笔误。
      // 例：src/pages/pp/PmcWorkbench.tsx:525 的 `发现：X\u3000·\u3000要回答：Y`。
      'no-irregular-whitespace': ['error', { skipJSXText: true }],

      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-empty-object-type': 'off',
      'no-empty': ['warn', { allowEmptyCatch: true }],

      // 源码里本来就有 `// eslint-disable-next-line react-hooks/exhaustive-deps`，
      // 说明写的人以为插件在装 —— 之前插件缺失，那些 disable 反而成了 "rule not found" 错误。
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
  {
    files: ['*.config.{js,ts}', 'vite.config.ts'],
    languageOptions: { globals: { ...globals.node } },
  },
]
