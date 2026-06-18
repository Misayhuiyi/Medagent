import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

function sanitizeUrl(url: string): string {
  if (/^javascript:/i.test(url) || /^data:/i.test(url)) return '#'
  return url
}

/** 预处理：规范 LaTeX 空格 + 合并表行内被换行拆散的单元格 */
function preprocess(raw: string): string {
  let text = raw
  // 1. 移除 LaTeX 公式内的换行（$...$ 块中 \n → 空格）
  text = text.replace(/\$([\s\S]*?)\$/g, (_, m: string) => '$' + m.replace(/\n/g, ' ') + '$')
  // 2. 规范 LaTeX 空格：\mathbf { X } → \mathbf{X}
  text = text.replace(/\\([a-zA-Z]+)\s+\{/g, '\\$1{')
  text = text.replace(/([_^])\s+\{/g, '$1{')
  // 3. 合并表格内被拆散的行：按 pipe 数识别完整行 vs 续行
  const lines = text.split('\n')
  const out: string[] = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    const pipeCount = (trimmed.match(/\|/g) || []).length
    const isSep = /^\|[-: |]+\|$/.test(trimmed)  // |---| 分隔行
    const isFullRow = pipeCount >= 4 || isSep     // 完整表行（≥4 个 |）
    if (isFullRow) {
      out.push(line)
    } else if (out.length > 0 && out[out.length - 1].trim().startsWith('|')) {
      // 续行：追加到上一表行
      out[out.length - 1] += trimmed
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