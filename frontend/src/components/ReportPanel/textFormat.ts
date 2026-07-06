const VALUE_LABELS: Record<string, string> = {
  summary: '摘要',
  status: '状态',
  note: '备注',
  notes: '备注',
  evidence: '依据',
  disease: '疾病',
  system: '系统',
  time: '时间',
  date: '日期',
  event: '事件',
  detail: '详情',
  details: '详情',
  conclusion: '结论',
  recommendation: '建议',
  reason: '理由',
  source: '来源',
}

function labelFor(key: string): string {
  return VALUE_LABELS[key] || key
}

export function formatClinicalValue(value: unknown, depth = 0): string {
  if (value == null || value === false) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value
      .map((item) => formatClinicalValue(item, depth + 1))
      .filter(Boolean)
      .join('\n')
  }
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>
    if (typeof obj.summary === 'string' && obj.summary.trim()) return obj.summary.trim()
    if (Array.isArray(obj.details)) return formatClinicalValue(obj.details, depth + 1)

    const parts = Object.entries(obj)
      .filter(([key, val]) => !key.startsWith('_') && val != null && val !== '')
      .map(([key, val]) => {
        const text = formatClinicalValue(val, depth + 1)
        if (!text) return ''
        return depth > 1 ? `${labelFor(key)}：${text.replace(/\n/g, '；')}` : `${labelFor(key)}：${text}`
      })
      .filter(Boolean)
    return parts.join(depth > 0 ? '；' : '\n')
  }
  return String(value)
}
