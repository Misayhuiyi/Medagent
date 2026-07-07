import { useEffect, useState, type ReactNode } from 'react'
import { Button, Tooltip, message } from 'antd'
import { usePatientStore, useReportStore, useEditStore, useChatStore } from '../../store'
import { fetchReport, saveReport } from '../../services/api'
import { useChat } from '../../hooks/useChat'
import { TAB_ORDER, TAB_LABELS, type TabName } from '../../types'
import TabHistory from './TabHistory'
import TabOverview from './TabOverview'
import TabTreatment from './TabTreatment'
import TabPrediction from './TabPrediction'
import TabCare from './TabCare'
import EditForm from './EditForm'
import DownloadButton from './DownloadButton'
import MarkdownRenderer from '../common/MarkdownRenderer'
import PipelineTiming from './PipelineTiming'
import ErrorBoundary from '../common/ErrorBoundary'

function EditIcon() {
  return (
    <svg viewBox="0 0 16 16" focusable="false" aria-hidden="true">
      <path d="M3 11.7V13h1.3l7.1-7.1-1.3-1.3L3 11.7Z" />
      <path d="M10.8 3.9 12 2.7c.3-.3.8-.3 1.1 0l.2.2c.3.3.3.8 0 1.1l-1.2 1.2" />
    </svg>
  )
}

function sanitizeReportMarkdown(content: string): string {
  if (!content) return ''
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const cleaned: string[] = []
  const structuredHeading = /^(?:#{1,6}\s*)?(?:[一二三四五六七八九十]+[、.．]\s*)?(?:完整结构化输出|合并输出JSON|结构化输出|JSON\s*输出)\s*$/i
  for (const line of lines) {
    const stripped = line.trim()
    if (structuredHeading.test(stripped)) break
    if (/^```json\b/i.test(stripped)) break
    if (/^```\s*$/.test(stripped)) continue
    if (
      stripped.includes('合并输出JSON') ||
      stripped.includes('【当前步骤上下文') ||
      stripped.includes('各子Skill输出文件')
    ) {
      break
    }
    if (/^所有\d*个?子Skill执行完毕/.test(stripped)) continue
    if (/^所有阶段已完成/.test(stripped)) continue
    if (/^现在让我整合/.test(stripped)) continue
    cleaned.push(line)
  }
  return cleaned.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

function findBalancedJson(text: string, startIndex: number): string | null {
  const stack: string[] = []
  let inString = false
  let escaped = false
  for (let i = startIndex; i < text.length; i++) {
    const ch = text[i]
    if (inString) {
      if (escaped) {
        escaped = false
      } else if (ch === '\\') {
        escaped = true
      } else if (ch === '"') {
        inString = false
      }
      continue
    }
    if (ch === '"') {
      inString = true
    } else if (ch === '{' || ch === '[') {
      stack.push(ch)
    } else if (ch === '}' || ch === ']') {
      const open = stack.pop()
      if ((ch === '}' && open !== '{') || (ch === ']' && open !== '[')) return null
      if (!stack.length) return text.slice(startIndex, i + 1)
    }
  }
  return null
}

function extractStructuredJsonFromText(text: string): Record<string, unknown> | null {
  if (!text) return null
  const candidates: string[] = []
  const fenced = text.matchAll(/```(?:json)?\s*([\s\S]*?)```/gi)
  for (const match of fenced) {
    const candidate = match[1]?.trim()
    if (candidate && /^[{[]/.test(candidate)) candidates.push(candidate)
  }

  const structuredMarkers = [
    '完整结构化输出',
    '合并输出JSON',
    '结构化输出',
    'JSON 输出',
    'JSON输出',
  ]
  for (const marker of structuredMarkers) {
    const markerIndex = text.indexOf(marker)
    if (markerIndex < 0) continue
    const startIndex = text.slice(markerIndex).search(/[{\[]/)
    if (startIndex >= 0) {
      const json = findBalancedJson(text, markerIndex + startIndex)
      if (json) candidates.push(json)
    }
  }

  const trimmed = text.trim()
  if (/^[{[]/.test(trimmed)) {
    const json = findBalancedJson(trimmed, 0)
    if (json) candidates.push(json)
  }

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // ignore malformed model output and keep the Markdown fallback
    }
  }
  return null
}

export default function ReportPanel() {
  const selectedId = usePatientStore((s) => s.selectedId)
  const selectedEncounter = usePatientStore((s) => s.selectedEncounter)
  const tabs = useReportStore((s) => s.tabs)
  const tabContents = useReportStore((s) => s.tabContents)
  const activeTab = useReportStore((s) => s.activeTab)
  const setActiveTab = useReportStore((s) => s.setActiveTab)
  const setReportData = useReportStore((s) => s.setReportData)
  const clearTabs = useReportStore((s) => s.clearTabs)
  const isEditing = useEditStore((s) => s.isEditing)
  const startEdit = useEditStore((s) => s.startEdit)
  const cancelEdit = useEditStore((s) => s.cancelEdit)
  const saveEdit = useEditStore((s) => s.saveEdit)
  const editFormData = useEditStore((s) => s.formData)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const { generateReport } = useChat(selectedId)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportLoadError, setReportLoadError] = useState('')

  useEffect(() => {
    let cancelled = false
    clearTabs()
    setReportLoadError('')
    if (selectedId) {
      setReportLoading(true)
      fetchReport(selectedId, selectedEncounter?.admission)
        .then((data) => {
          if (!cancelled) setReportData(data)
        })
        .catch((err) => {
          if (!cancelled) {
            console.warn('Failed to load report:', err)
            setReportLoadError('报告加载失败，请稍后重试')
          }
        })
        .finally(() => {
          if (!cancelled) setReportLoading(false)
        })
    }
    return () => {
      cancelled = true
    }
  }, [selectedId, selectedEncounter?.admission, setReportData, clearTabs])

  const handleSave = async () => {
    const formData = saveEdit()
    if (!selectedId) return
    try {
      const merged = { ...tabs, ...formData }
      await saveReport(selectedId, merged, selectedEncounter?.admission)
      setReportData(merged)
    } catch (err) {
      console.error('Failed to save report:', err)
      message.error('保存失败，请重试')
    }
  }

  const STRUCTURED_KEYS: Partial<Record<TabName, string[]>> = {
    'patient-history': [
      'visit_count', 'present_illness', 'past_history', 'allergy_history', 'personal_history',
      'family_history', 'treatment_history', 'patient_info', 'lesion_numbering',
      'timeline', 'tumor_size_chart', 'tumorSizeChart', 'tumorSize', 'tumor_size',
    ],
    'patient-overview': [
      'chief_complaint', 'physical_examination', 'auxiliary_examination', 'diagnosis',
      'ai_tumor_burden', 'ai_efficacy', 'ai_adverse_events', 'ai_comorbidity',
      'ecog_score', 'chronic_management_triangle', 'supplemental_tests',
    ],
    'treatment-plan': [
      'treatment_plans', 'adverse_reaction_plan', 'comorbidity_plan',
      'clinical_trials', 'decision_path', 'drug_classification',
    ],
    'efficacy-prediction': [
      'tumor_prediction', 'adverse_prediction', 'prognosis',
      'adaptive_prediction_summary', 'adaptive_monitoring_plan', 'prognostic_factors',
    ],
    'suggestions': [
      'psychological_care', 'health_measures', 'tcm_suggestions',
      'nursing_care', 'follow_up_plan', 'ai_recommendations', 'patient_education',
    ],
  }

  const CHINESE_TO_ENGLISH: Record<string, string> = {
    '现病史': 'present_illness', '既往史': 'past_history', '过敏史': 'allergy_history',
    '个人史': 'personal_history', '家族史': 'family_history', '治疗史': 'treatment_history',
    '主诉': 'chief_complaint', '体格检查': 'physical_examination', '辅助检查': 'auxiliary_examination',
    '肿瘤负荷': 'ai_tumor_burden', '疗效评估': 'ai_efficacy', '不良反应': 'ai_adverse_events',
    '合并症': 'ai_comorbidity', '诊断': 'diagnosis', '补充资料': 'supplemental_tests',
    '治疗方案': 'treatment_plans', '不良反应处理': 'adverse_reaction_plan', '合并症处理': 'comorbidity_plan',
    '临床试验': 'clinical_trials',
    '肿瘤预测': 'tumor_prediction', '不良反应预测': 'adverse_prediction', '预后': 'prognosis',
    '预后因素': 'prognostic_factors',
    '时间线': 'timeline', '肿瘤大小趋势': 'tumor_size_chart', '肿瘤大小': 'tumor_size_chart',
    '肿瘤尺寸': 'tumor_size_chart',
    '心理关怀': 'psychological_care', '健康措施': 'health_measures', '中医建议': 'tcm_suggestions',
    '护理': 'nursing_care', '随访': 'follow_up_plan',
  }

  function normalizeTabData(raw: Record<string, unknown>): Record<string, unknown> {
    const normalized: Record<string, unknown> = { ...raw }
    for (const [cnKey, enKey] of Object.entries(CHINESE_TO_ENGLISH)) {
      if (cnKey in raw && !(enKey in raw)) {
        normalized[enKey] = raw[cnKey]
      }
    }
    return normalized
  }

  /** 渲染 Tab 内容：优先结构化(含图表)，次选 Markdown，最后 JSON 回退。
   *  与 old_MedAgent 保持一致的渲染策略：有结构化字段 → FigmaReportCard + ECharts；
   *  无结构化字段 → Markdown 纯文本。
   */
  function renderTabContent(
    tab: TabName,
    StructuredComponent: React.ComponentType<any>,
    data: unknown,
  ): ReactNode {
    if (!data) {
      return <div className="empty-state">等待生成...</div>
    }
    const raw = data as Record<string, unknown>
    const record = normalizeTabData(raw)

    // 尝试从 wrapper 对象（{step, result, _content}）中提取结构化数据
    // 将 result 字段作为 JSON 尝试解析，如果成功则合并到 record 中以供结构化检测
    const enhanceFromWrapper = () => {
      const toTry = [record.result, record._content, record.content]
      for (const val of toTry) {
        if (typeof val !== 'string') continue
        const parsed = extractStructuredJsonFromText(val)
        if (parsed) {
          Object.assign(record, normalizeTabData(parsed))
        }
      }
    }
    // 仅当数据看起来是后端包装对象时才尝试提取
    if ('step' in record && Object.keys(record).length <= 5) {
      enhanceFromWrapper()
    } else if (typeof record._content === 'string' || typeof record.content === 'string' || typeof record.result === 'string') {
      enhanceFromWrapper()
    }

    // 1) 结构化渲染：有特征字段就用组件（含 ECharts 图表、FigmaReportCard）
    const keyFields = (STRUCTURED_KEYS[tab] || []).filter(k => !/[一-鿿]/.test(k))
    const hasStructured = keyFields.some(k => k in record)
    if (hasStructured) {
      try {
        // _content 作为额外 Markdown 附录追加（当它包含结构化组件无法展示的信息时）
        const mdAppendix: string = sanitizeReportMarkdown(String(record._content || record.content || ''))
        const isRawJson = mdAppendix.trim().startsWith('{') || mdAppendix.trim().startsWith('[{')
        const structuredText = keyFields
          .map((k) => record[k])
          .filter(Boolean)
          .map((v) => typeof v === 'string' ? v : JSON.stringify(v))
          .join('\n')
        const appendixPreview = mdAppendix.trim().slice(0, 160)
        const showAppendix = mdAppendix.length >= 50 && !isRawJson && (
          !structuredText || !structuredText.includes(appendixPreview)
        )
        return (
          <>
            <StructuredComponent data={record} />
            {showAppendix && (
              <div className="report-tab-content report-tab-content--appendix">
                <MarkdownRenderer content={mdAppendix} />
              </div>
            )}
          </>
        )
      } catch {
        // 失败则降级
      }
    }

    // 2) Markdown 回退（仅当内容是 Markdown 文本时才渲染）
    const mdContent: string = sanitizeReportMarkdown(String(record._content || record.content || record.result || ''))
    const isRawJson = mdContent.trim().startsWith('{') || mdContent.trim().startsWith('[{')
    if (mdContent.length >= 50 && !isRawJson) {
      return (
        <div className="report-tab-content">
          <MarkdownRenderer content={mdContent} />
        </div>
      )
    }

    // 3) JSON 兜底
    return <div className="empty-state">暂无可展示的报告正文</div>
  }

  const dataForTab = (tab: TabName) => {
    const data = tabs[tab]
    if (data) return data
    const content = tabContents[tab]
    return content ? { content } : undefined
  }

  const tabContent: Record<TabName, ReactNode> = {
    'patient-history': renderTabContent('patient-history', TabHistory, dataForTab('patient-history')),
    'patient-overview': renderTabContent('patient-overview', TabOverview, dataForTab('patient-overview')),
    'treatment-plan': renderTabContent('treatment-plan', TabTreatment, dataForTab('treatment-plan')),
    'efficacy-prediction': renderTabContent('efficacy-prediction', TabPrediction, dataForTab('efficacy-prediction')),
    'suggestions': renderTabContent('suggestions', TabCare, dataForTab('suggestions')),
  }

  const handleGenerate = async () => {
    if (!selectedId || isStreaming) return
    await generateReport('请基于当前选中时间点的患者资料，并结合此前时间点的既往报告，生成本时间点的患者病史、患者概况、治疗方案、疗效预测和其他建议，并更新右侧报告。', selectedEncounter)
  }

  if (!selectedId) {
    return (
      <div className="report-panel">
        <div className="empty-state">暂无报告</div>
      </div>
    )
  }

  return (
    <div className="report-panel">
      <div className="report-panel__header">
        <div className="result-tabs">
          {TAB_ORDER.map((tab) => (
            <button
              key={tab}
              className={`result-tab ${activeTab === tab ? 'is-active' : ''}`}
              type="button"
              onClick={() => setActiveTab(tab)}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>
        <div className="report-edit-actions">
          {isEditing ? (
            <>
              <Button size="small" onClick={cancelEdit}>取消</Button>
              <Button size="small" type="primary" onClick={handleSave}>保存</Button>
            </>
          ) : (
            <Tooltip title="编辑报告">
              <Button size="small" icon={<EditIcon />} onClick={() => startEdit(tabs)} />
            </Tooltip>
          )}
        </div>
      </div>
      <div className="report-panel__body">
        {reportLoading ? (
          <div className="empty-state">正在加载报告...</div>
        ) : reportLoadError ? (
          <div className="empty-state">{reportLoadError}</div>
        ) : Object.keys(tabs).length === 0 ? (
          <div className="empty-state">{isStreaming ? '正在生成报告，完成后将逐标签页展示...' : '发送消息后 AI 将逐标签页生成报告'}</div>
        ) : isEditing && editFormData[activeTab] ? (
          <EditForm tab={activeTab} data={editFormData[activeTab] as unknown as Record<string, unknown>} />
        ) : (
          <ErrorBoundary key={activeTab}>{tabContent[activeTab]}</ErrorBoundary>
        )}
      </div>
      <div className="report-panel__footer">
        <DownloadButton patientId={selectedId} onGenerate={handleGenerate} />
      </div>
      <PipelineTiming patientId={selectedId} />
    </div>
  )
}
