import type { ReactNode } from 'react'
import type { SemanticHighlight, SemanticHighlightCarrier } from '../../types'

const COLOR_CLASS: Record<SemanticHighlight['color'], string> = {
  red: 'clinical-mark clinical-mark--red',
  blue: 'clinical-mark clinical-mark--blue',
  green: 'clinical-mark clinical-mark--green',
}

const AUTO_TERMS: Record<SemanticHighlight['color'], string[]> = {
  red: [
    '免疫检查点抑制相关肺炎', '免疫相关性肺炎', '肺泡蛋白沉积症', '炎症后肺纤维化',
    '不良反应', '毒副反应', '肺炎', '间质性炎症', '间质性肺病', '肺纤维化',
    '气胸', '咯血', '发热', '感染', '高血糖', '肝功能异常', '风险', '禁忌', '警惕', '恶化',
  ],
  blue: [
    '左肺腺癌', '肺恶性肿瘤', '肿瘤负荷', '原发灶', '靶病灶', '肿瘤', '病灶', '结节',
    '分期', '复发', '进展', '转移', '淋巴结', 'KRAS G12C', 'KRAS', 'TP53', 'PD-L1', 'PDL1', 'TMB', 'RECIST', 'CT', 'PET-CT',
  ],
  green: [
    '新辅助治疗', '辅助治疗', '维持治疗', '抗血管生成', '靶向治疗', '免疫治疗',
    '治疗', '疗效', '缓解', '缩小', '稳定', '改善', '随访', '复查', '手术',
    '化疗', '培美曲塞', '卡铂', '信迪利单抗', '贝伐珠单抗', '索托拉西布', '阿达格拉西布', '康复', '护理', '监测',
  ],
}

export function highlightsFrom(data?: SemanticHighlightCarrier): SemanticHighlight[] {
  return Array.isArray(data?._semantic_highlights) ? data._semantic_highlights : []
}

export function autoHighlights(text: string): SemanticHighlight[] {
  const found: SemanticHighlight[] = []
  for (const [color, terms] of Object.entries(AUTO_TERMS) as Array<[SemanticHighlight['color'], string[]]>) {
    for (const term of terms) {
      if (text.includes(term)) found.push({ text: term, color, reason: color === 'red' ? '不良反应/风险' : color === 'blue' ? '肿瘤负荷' : '治疗及疗效' })
    }
  }
  return found
}

function renderHighlighted(text: string, highlights: SemanticHighlight[]): ReactNode[] {
  if (!text || !highlights.length) return [text]
  const ranges: Array<{ start: number; end: number; color: SemanticHighlight['color']; reason?: string }> = []

  for (const h of highlights) {
    if (!h.text || !h.color) continue
    let from = 0
    while (from < text.length) {
      const start = text.indexOf(h.text, from)
      if (start < 0) break
      ranges.push({ start, end: start + h.text.length, color: h.color, reason: h.reason })
      from = start + h.text.length
    }
  }

  const selected: typeof ranges = []
  const occupied: Array<{ start: number; end: number }> = []
  for (const range of ranges.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start))) {
    if (occupied.some((used) => range.start < used.end && range.end > used.start)) continue
    selected.push(range)
    occupied.push({ start: range.start, end: range.end })
  }
  selected.sort((a, b) => a.start - b.start)

  const nodes: ReactNode[] = []
  let cursor = 0
  selected.forEach((range, index) => {
    if (cursor < range.start) nodes.push(text.slice(cursor, range.start))
    nodes.push(
      <mark key={`${range.start}-${range.end}-${index}`} className={COLOR_CLASS[range.color]} title={range.reason}>
        {text.slice(range.start, range.end)}
      </mark>,
    )
    cursor = range.end
  })
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

export default function ClinicalText({
  text,
  highlights = [],
  compact = false,
}: {
  text?: string | number | null
  highlights?: SemanticHighlight[]
  compact?: boolean
}) {
  const value = text == null ? '' : String(text).trim()
  if (!value) return null
  const effectiveHighlights = highlights.length ? highlights : autoHighlights(value)

  const paragraphs = value
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)

  return (
    <div className={compact ? 'clinical-text clinical-text--compact' : 'clinical-text'}>
      {paragraphs.map((line, index) => (
        <p key={`${line.slice(0, 24)}-${index}`}>{renderHighlighted(line, effectiveHighlights)}</p>
      ))}
    </div>
  )
}
