import { useEffect, type ReactNode } from 'react'
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

export default function ReportPanel() {
  const selectedId = usePatientStore((s) => s.selectedId)
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

  useEffect(() => {
    clearTabs()
    if (selectedId) {
      fetchReport(selectedId)
        .then((data) => setReportData(data))
        .catch((err) => console.warn('Failed to load report:', err))
    }
  }, [selectedId, setReportData, clearTabs])

  const handleSave = async () => {
    const formData = saveEdit()
    if (!selectedId) return
    try {
      const merged = { ...tabs, ...formData }
      await saveReport(selectedId, merged)
      setReportData(merged)
    } catch (err) {
      console.error('Failed to save report:', err)
      message.error('保存失败，请重试')
    }
  }

  const STRUCTURED_KEYS: Partial<Record<TabName, string[]>> = {
    'patient-history': [
      'visit_count', 'present_illness', 'past_history', 'allergy_history', 'personal_history', 'family_history',
      '现病史', '既往史', '过敏史', '个人史', '家族史',
    ],
    'patient-overview': [
      'chief_complaint', 'physical_examination', 'diagnosis',
      '主诉', '体格检查', '诊断', '肿瘤负荷', 'ECOG',
    ],
    'treatment-plan': [
      'treatment_plans', 'adverse_reaction_plan', 'comorbidity_plan',
      '治疗方案', '决策路径', '指南匹配',
    ],
    'efficacy-prediction': [
      'tumor_prediction', 'adverse_prediction', 'prognosis',
      '疗效预测', '预后', 'ORR', 'PFS', 'OS',
    ],
    'suggestions': [
      'psychological_care', 'health_measures', 'tcm_suggestions',
      '心理关怀', '健康措施', '中医建议', '护理', '随访',
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

  /** 渲染 Tab 内容：优先结构化(含图表)，次选 Markdown，最后 JSON 回退 */
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

    // 后端常见包装：{"step": "...", "result": "...", "_content": "..."}。
    // 这不代表生成失败，优先按 Markdown 正常展示。
    if ('step' in record && ('result' in record || '_content' in record) && Object.keys(record).length <= 5) {
      const wrappedContent = String(record._content || record.result || '')
      return (
        <div className="report-tab-content">
          <MarkdownRenderer content={wrappedContent || '本页签已完成，但暂无可展示内容。'} />
        </div>
      )
    }

    // 1) 结构化渲染：有特征字段就用组件（含 ECharts 图表）
    const keyFields = (STRUCTURED_KEYS[tab] || []).filter(k => !/[一-鿿]/.test(k))
    const hasStructured = keyFields.some(k => k in record)
    if (hasStructured) {
      try {
        // _content 包含原始 JSON 时不需要追加（LLM 输出中已有结构化字段）
        const mdAppendix: string = String(record._content || record.content || '')
        const isRawJson = mdAppendix.trim().startsWith('{') || mdAppendix.trim().startsWith('[{')
        const showAppendix = mdAppendix.length >= 50 && !isRawJson && !keyFields.some(k => {
          const v = record[k]
          return (typeof v === 'string' && v.length > mdAppendix.length * 0.4) ||
                 (typeof v === 'object' && v !== null && !Array.isArray(v))
        })
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

    // 2) Markdown 回退（仅当 _content 不是原始 JSON 时才渲染）
    const mdContent: string = String(record._content || record.content || record.result || '')
    const isRawJson = mdContent.trim().startsWith('{') || mdContent.trim().startsWith('[{')
    if (mdContent.length >= 50 && !isRawJson) {
      return (
        <div className="report-tab-content">
          <MarkdownRenderer content={mdContent} />
        </div>
      )
    }

    // 3) JSON 兜底
    return (
      <div className="report-tab-content">
        <MarkdownRenderer content={'```json\n' + JSON.stringify(record, null, 2) + '\n```'} />
      </div>
    )
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
    await generateReport('请基于患者全部病历、检查报告和当前对话，生成患者病史、患者概况、治疗方案、疗效预测和其他建议，并更新右侧报告。')
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
        {Object.keys(tabs).length === 0 ? (
          <div className="empty-state">发送消息后 AI 将逐标签页生成报告</div>
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
