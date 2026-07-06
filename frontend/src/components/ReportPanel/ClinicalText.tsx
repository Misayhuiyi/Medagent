import type { ReactNode } from 'react'
import type { SemanticHighlight, SemanticHighlightCarrier } from '../../types'

const COLOR_CLASS: Record<SemanticHighlight['color'], string> = {
  red: 'clinical-mark clinical-mark--red',
  blue: 'clinical-mark clinical-mark--blue',
  green: 'clinical-mark clinical-mark--green',
}

export function highlightsFrom(data?: SemanticHighlightCarrier): SemanticHighlight[] {
  return Array.isArray(data?._semantic_highlights) ? data._semantic_highlights : []
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

  const paragraphs = value
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)

  return (
    <div className={compact ? 'clinical-text clinical-text--compact' : 'clinical-text'}>
      {paragraphs.map((line, index) => (
        <p key={`${line.slice(0, 24)}-${index}`}>{renderHighlighted(line, highlights)}</p>
      ))}
    </div>
  )
}
