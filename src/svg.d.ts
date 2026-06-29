declare module '*.svg?raw' {
  const content: string
  export default content
}

// vite-svg-loader 已移除，不再支持直接作为组件导入
// 统一使用 import x from './x.svg?raw' + <SvgIcon :svg="x" />
