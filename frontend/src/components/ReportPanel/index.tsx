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

  const tabContent: Record<TabName, ReactNode> = {
    'patient-history': <TabHistory data={tabs['patient-history']} />,
    'patient-overview': <TabOverview data={tabs['patient-overview']} />,
    'treatment-plan': <TabTreatment data={tabs['treatment-plan']} />,
    'efficacy-prediction': <TabPrediction data={tabs['efficacy-prediction']} />,
    'suggestions': <TabCare data={tabs.suggestions} />,
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
