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
  smoking: '吸烟史',
  alcohol: '饮酒史',
  drinking: '饮酒史',
  occupationalExposure: '职业暴露史',
  occupational_exposure: '职业暴露史',
  environmentalFactors: '环境暴露史',
  environmental_factors: '环境暴露史',
  maritalStatus: '婚育史',
  marital_status: '婚育史',
  vaccination: '预防接种史',
  yearsSmoked: '吸烟年限',
  years_smoked: '吸烟年限',
  cigarettesPerDay: '每日吸烟量',
  cigarettes_per_day: '每日吸烟量',
  packYears: '吸烟指数',
  pack_years: '吸烟指数',
  quitDuration: '戒烟时长',
  quit_duration: '戒烟时长',
  noKnownAllergy: '无明确过敏史',
  notMentioned: '资料未提及',
}

function labelFor(key: string): string {
  return VALUE_LABELS[key] || key
}

export function formatClinicalValue(value: unknown, depth = 0): string {
  if (value == null || value === false) return ''
  if (typeof value === 'string') return cleanClinicalText(value)
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
    const natural = naturalizeStructuredObject(obj)
    if (natural) return natural

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

function cleanClinicalText(value: string): string {
  return value
    .replace(/([：:；;，,（(]\s*)数据[：:]/g, '$1')
    .replace(/^数据[：:]\s*/gm, '')
    .replace(/([：:])\s*状态[：:]\s*/g, '$1')
    .trim()
}

function naturalizeStructuredObject(obj: Record<string, unknown>): string {
  const keys = new Set(Object.keys(obj))
  if (keys.has('smoking') || keys.has('alcohol') || keys.has('drinking') || keys.has('occupationalExposure') || keys.has('environmentalFactors')) {
    const parts: string[] = []
    const smoking = obj.smoking
    if (isPlainObject(smoking)) {
      const text = smokingText(smoking)
      if (text) parts.push(`吸烟史：${text}`)
    }

    const alcohol = obj.alcohol ?? obj.drinking
    if (isPlainObject(alcohol)) {
      const text = alcoholText(alcohol)
      if (text) parts.push(`饮酒史：${text}`)
    }

    const occupational = obj.occupationalExposure ?? obj.occupational_exposure
    if (isPlainObject(occupational)) {
      const text = simpleStatusNote(occupational)
      if (text) parts.push(`职业暴露史：${text}`)
    }

    const environmental = obj.environmentalFactors ?? obj.environmental_factors
    if (isPlainObject(environmental)) {
      const text = simpleStatusNote(environmental)
      if (text) parts.push(`环境暴露史：${text}`)
    }

    const other = obj.other
    if (isPlainObject(other)) {
      for (const key of ['maritalStatus', 'marital_status', 'vaccination']) {
        const value = other[key]
        const text = formatClinicalValue(value)
        if (text) parts.push(`${labelFor(key)}：${text}`)
      }
    }

    if (parts.length) return `${parts.join('；')}。`
  }

  if (keys.has('noKnownAllergy') || keys.has('notMentioned')) {
    if (obj.noKnownAllergy) return '否认明确食物或药物过敏史。'
    if (obj.notMentioned) return '资料未提及明确过敏史，建议补充核实。'
  }

  return ''
}

function smokingText(obj: Record<string, unknown>): string {
  const status = formatClinicalValue(obj.status)
  const years = obj.yearsSmoked ?? obj.years_smoked
  const amount = obj.cigarettesPerDay ?? obj.cigarettes_per_day
  const packYears = obj.packYears ?? obj.pack_years
  const quitDuration = obj.quitDuration ?? obj.quit_duration
  const parts = [
    status,
    years ? `吸烟${formatClinicalValue(years)}年` : '',
    amount ? `约${formatClinicalValue(amount)}支/日` : '',
    packYears ? `吸烟指数约${formatClinicalValue(packYears)}包年` : '',
    quitDuration ? `戒烟约${formatClinicalValue(quitDuration)}` : '',
  ].filter(Boolean)
  return parts.join('，')
}

function alcoholText(obj: Record<string, unknown>): string {
  const detail = formatClinicalValue(obj.detail)
  if (detail) return detail
  return [
    formatClinicalValue(obj.status),
    formatClinicalValue(obj.duration ?? obj.years),
    formatClinicalValue(obj.amount ?? obj.quantity),
  ].filter(Boolean).join('，')
}

function simpleStatusNote(obj: Record<string, unknown>): string {
  const status = formatClinicalValue(obj.status)
  const note = formatClinicalValue(obj.note)
  if (status && note) return `${status}（${note}）`
  return status || note || ''
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
