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

  /** 渲染 Tab 内容：优先结构化渲染，无结构化数据时回退到 Markdown */
  function renderTabContent(
    _tab: TabName,
    StructuredComponent: React.ComponentType<{ data?: unknown }>,
    data: unknown,
  ): ReactNode {
    if (!data) {
      return <div className="empty-state">等待生成...</div>
    }
    const record = data as Record<string, unknown>
    // 检查是否有原始 markdown 内容（_content / content 字段）
    const rawContent = (record._content || record.content) as string | undefined
    const hasStructured = Object.keys(record).filter(k => k !== '_content' && k !== 'content' && k !== 'step' && k !== 'display_name' && k !== 'status').length > 0

    if (hasStructured) {
      return <StructuredComponent data={record as never} />
    }
    if (rawContent) {
      return (
        <div className="report-tab-content">
          <MarkdownRenderer content={rawContent} />
        </div>
      )
    }
    return <div className="empty-state">无内容</div>
  }

  const tabContent: Record<TabName, ReactNode> = {
    'patient-history': renderTabContent('patient-history', TabHistory, tabs['patient-history']),
    'patient-overview': renderTabContent('patient-overview', TabOverview, tabs['patient-overview']),
    'treatment-plan': renderTabContent('treatment-plan', TabTreatment, tabs['treatment-plan']),
    'efficacy-prediction': renderTabContent('efficacy-prediction', TabPrediction, tabs['efficacy-prediction']),
    'suggestions': renderTabContent('suggestions', TabCare, tabs.suggestions),
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
          tabContent[activeTab]
        )}
      </div>
      <div className="report-panel__footer">
        <DownloadButton patientId={selectedId} onGenerate={handleGenerate} />
      </div>
    </div>
  )
}
