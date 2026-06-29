/**
 * svg-clean.mjs
 * 用法：node svg-clean.mjs [文件或目录]
 *   node svg-clean.mjs src/icons/search.svg      # 处理单个文件
 *   node svg-clean.mjs src/icons                 # 处理目录下所有 .svg
 *   node svg-clean.mjs                           # 默认处理 src/icons
 *
 * 转换内容：
 *   - 移除 <defs> 及其所有子内容（filter、clipPath 等）
 *   - 移除所有元素上的 filter="url(...)" 属性
 *   - 移除所有 id 属性（避免多实例冲突）
 *   - 移除固定 width/height，只保留 viewBox
 *   - 确保根节点有 xmlns
 *   - 不改动 fill、stroke、path 数据
 */

import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function cleanSvg(content) {
  let out = content

  // 移除 <defs>...</defs>
  out = out.replace(/<defs[\s\S]*?<\/defs>/gi, '')

  // 移除所有元素上的 filter="url(...)" 属性
  out = out.replace(/\s+filter="url\([^"]*\)"/g, '')

  // 移除所有 id="..." 属性
  out = out.replace(/\s+id="[^"]*"/g, '')

  // 移除根 <svg> 上的固定 width 和 height（保留 viewBox）
  out = out.replace(/(<svg[^>]*?)\s+width="[^"]*"/i, '$1')
  out = out.replace(/(<svg[^>]*?)\s+height="[^"]*"/i, '$1')

  // 确保根 <svg> 有 xmlns
  if (!out.includes('xmlns=')) {
    out = out.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"')
  }

  // 清理多余空行
  out = out.replace(/\n\s*\n/g, '\n').trim()

  return out
}

function processFile(filePath) {
  const original = fs.readFileSync(filePath, 'utf8')
  const cleaned = cleanSvg(original)
  if (cleaned !== original) {
    fs.writeFileSync(filePath, cleaned, 'utf8')
    console.log(`✓ ${path.basename(filePath)}`)
  } else {
    console.log(`- ${path.basename(filePath)} (无需修改)`)
  }
}

function processTarget(target) {
  const abs = path.resolve(__dirname, target)
  const stat = fs.statSync(abs)
  if (stat.isDirectory()) {
    const files = fs.readdirSync(abs).filter(f => f.endsWith('.svg'))
    if (files.length === 0) { console.log('目录下没有 .svg 文件'); return }
    files.forEach(f => processFile(path.join(abs, f)))
    console.log(`\n共处理 ${files.length} 个文件`)
  } else {
    processFile(abs)
  }
}

const arg = process.argv[2] || 'src/icons'
processTarget(arg)
