import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

function sanitizeUrl(url: string): string {
  if (/^javascript:/i.test(url) || /^data:/i.test(url)) return '#'
  return url
}

/** 检测 CSV 行块并转换为 Markdown 管道表 */
function csvToPipeTables(text: string): string {
  const lines = text.split('\n')
  const result: string[] = []
  let i = 0

  while (i < lines.length) {
    // 收集候选 CSV 块：连续的行，每行相同逗号数
    const block: { line: string; cols: string[] }[] = []
    let colCount = -1

    while (i < lines.length) {
      const trimmed = lines[i].trim()
      if (!trimmed) break
      // 跳过已处理为 | 的表格、块级标记、HTML
      if (/^\|/.test(trimmed) || /^(#{1,6}\s|>|```|[-*]{3,}|<\/?)/.test(trimmed)) break
      // 必须有 ≥2 个逗号（≥3 列）
      const commas = (trimmed.match(/,/g) || []).length
      if (commas < 2) break
      const cols = trimmed.split(',')
      if (colCount === -1) colCount = cols.length
      if (cols.length !== colCount) break
      // 避免误吞长句（不含中文句号感叹号等）
      if (/[。！？；]/.test(trimmed) && cols.length < 4) break
      // 避免误吞单列表格
      if (cols.length >= 4 && /^[^,]+,[^,]+,[^,]+,[^,]+$/.test(trimmed) && /[。！？]/.test(trimmed)) break

      block.push({ line: trimmed, cols })
      i++
    }

    if (block.length >= 3) {
      // 表头 = 第一行，数据行 = 后续行
      const header = '| ' + block[0].cols.join(' | ') + ' |'
      const sep = '| ' + block[0].cols.map(() => '---').join(' | ') + ' |'
      const rows = block.slice(1).map(r => '| ' + r.cols.join(' | ') + ' |')
      result.push('', header, sep, ...rows, '')
    } else {
      if (block.length > 0) result.push(...block.map(b => b.line))
      else result.push(lines[i])
      i++
    }
  }
  return result.join('\n')
}

/** 预处理：LaTeX + 表格合并 + HTML details 转 Markdown + CSV 转表 */
function preprocess(raw: string): string {
  let text = raw

  // 0a. HTML <details><summary> → **标题**
  text = text.replace(/<details>\s*<summary>\s*(.*?)\s*<\/summary>\s*([\s\S]*?)\s*<\/details>/gi,
    (_, title, content) => '**' + title.replace(/<\/?b>/gi, '').trim() + '**\n\n' + content.trim() + '\n'
  )
  text = text.replace(/<summary>\s*(.*?)\s*<\/summary>/gi, '**$1**')
  text = text.replace(/<\/?details\s*>/gi, '')
  // 0b. 孤立的 <b> </b> 转为 ** **
  text = text.replace(/<b>\s*(.*?)\s*<\/b>/gi, '**$1**')
  // 0c. CSV → 管道表
  text = csvToPipeTables(text)

  // 1. LaTeX 公式内换行 → 空格
  text = text.replace(/\$([\s\S]*?)\$/g, (_, m: string) => '$' + m.replace(/\n/g, ' ') + '$')
  // 2. 规范 LaTeX 空格
  text = text.replace(/\\([a-zA-Z]+)\s+\{/g, '\\$1{')
  text = text.replace(/([_^])\s+\{/g, '$1{')

  // 3. 合并拆散的表行
  const lines = text.split('\n')
  const out: string[] = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    const pipeCount = (trimmed.match(/\|/g) || []).length
    const isSep = /^\|[-: |]+\|$/.test(trimmed)
    const isFullRow = pipeCount >= 4 || isSep
    const isBlockMarker = /^(#{1,6}\s|>|[-*_]{2,}|[-*]\s|```|~~~|\d+\.\s)/.test(trimmed)
    const isBrokenSep = /^\|[-:\s]*$/.test(trimmed)
    const prevLine = out.length > 0 ? out[out.length - 1].trim() : ''
    const prevIsSep = /^\|[-: |]+\|$/.test(prevLine)
    const isSingleCell = /^\|[^|\n]*$/.test(trimmed) && !isSep

    if (isFullRow || isBlockMarker || isBrokenSep) {
      out.push(line)
    } else if (isSingleCell && !prevIsSep && prevLine.startsWith('|')) {
      out[out.length - 1] += ' ' + trimmed
    } else {
      out.push(line)
    }
  }
  return out.join('\n')
}

interface Props { content: string }

export default function MarkdownRenderer({ content }: Props) {
  const clean = preprocess(content)

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        a: ({ href, children, ...rest }) => (
          <a href={href ? sanitizeUrl(href) : href} target="_blank" rel="noopener noreferrer" {...rest}>{children}</a>
        ),
        h1: ({ children, ...rest }) => <h3 {...rest}>{children}</h3>,
        h2: ({ children, ...rest }) => <h3 {...rest}>{children}</h3>,
        table: ({ children, ...rest }) => (
          <div className="trace-table-wrap">
            <table {...rest}>{children}</table>
          </div>
        ),
      }}
    >
      {clean}
    </ReactMarkdown>
  )
}
