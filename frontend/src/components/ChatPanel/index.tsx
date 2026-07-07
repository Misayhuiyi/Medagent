import { useEffect, useRef, useState, useMemo } from 'react'
import { message } from 'antd'
import { usePatientStore, useChatStore } from '../../store'
import { fetchChatHistory } from '../../services/api'
import { useChat } from '../../hooks/useChat'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import type { EncounterFilter } from '../../types'

function CloseIcon() {
  return (
    <svg viewBox="0 0 16 16" focusable="false" aria-hidden="true">
      <path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" />
    </svg>
  )
}

function AddIcon() {
  return (
    <svg viewBox="0 0 22 22" focusable="false" aria-hidden="true">
      <path d="M11 4.6v12.8M4.6 11h12.8" />
    </svg>
  )
}

function formatDate(date: string) {
  if (!date) return ''
  const parts = date.split('-')
  if (parts.length !== 3) return date
  return `${parts[0]}-${Number(parts[1])}-${Number(parts[2])}`
}

function encounterLabel(encounter: EncounterFilter) {
  if (encounter.label) return encounter.label
  const date = formatDate(encounter.admission)
  if (encounter.type === 'outpatient') return `门诊时间 ${date}`
  if (encounter.type === 'discharge') return `出院时间 ${date}`
  return `入院时间 ${date}`
}

export default function ChatPanel() {
  const selectedId = usePatientStore((s) => s.selectedId)
  const patients = usePatientStore((s) => s.patients)
  const selectPatient = usePatientStore((s) => s.selectPatient)
  const removePatient = usePatientStore((s) => s.removePatient)
  const selectedEncounter = usePatientStore((s) => s.selectedEncounter)
  const setSelectedEncounter = usePatientStore((s) => s.setSelectedEncounter)
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const addMessages = useChatStore((s) => s.addMessages)
  const clearMessages = useChatStore((s) => s.clearMessages)
  const setThinkingTime = useChatStore((s) => s.setThinkingTime)
  const { sendMessage, generateReport, abort } = useChat(selectedId)
  const [showThinking, setShowThinking] = useState(true)

  // 当前患者的就诊记录列表
  const selectedPatient = patients.find((p) => p.id === selectedId)
  const encounterList = useMemo(() => {
    const encs = selectedPatient?.encounters || []
    return encs.map((enc, i) => ({
      index: i,
      admission: enc.admission,
      discharge: enc.discharge,
      type: enc.type,
      source_admission: enc.source_admission,
      label: encounterLabel(enc),
    }))
  }, [selectedPatient])

  // 切换就诊选择
  const handleSelectEncounter = (encounter: EncounterFilter | null) => {
    setSelectedEncounter(encounter)
  }

  // 生成报告 — 传入当前选择的就诊时间
  const handleGenerateReport = () => {
    if (selectedEncounter) {
      const selectedLabel = encounterLabel(selectedEncounter)
      generateReport(
        `请基于患者该次就诊（${selectedLabel}）的病历、检查报告，生成患者病史、患者概况、治疗方案、疗效预测和其他建议，并更新右侧报告。`,
        selectedEncounter,
      )
    } else {
      generateReport('请基于患者全部病历、检查报告和当前对话，生成患者病史、患者概况、治疗方案、疗效预测和其他建议，并更新右侧报告。')
    }
  }

  // Thinking timer
  const thinkingStart = useRef(0)
  useEffect(() => {
    if (isStreaming) {
      thinkingStart.current = Date.now()
      setThinkingTime(0)
      const timer = setInterval(() => setThinkingTime(Math.round((Date.now() - thinkingStart.current) / 1000)), 1000)
      return () => clearInterval(timer)
    }
  }, [isStreaming, setThinkingTime])

  useEffect(() => {
    abort()
    if (selectedId) {
      fetchChatHistory(selectedId)
        .then((msgs) => {
          clearMessages()
          if (msgs.length > 0) addMessages(msgs)
        })
        .catch((err) => {
          console.warn('Failed to load chat history:', err)
          clearMessages()
        })
    } else {
      clearMessages()
    }
  }, [selectedId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!selectedId) {
    return (
      <div className="chat-panel">
        <div className="empty-state">请选择患者</div>
      </div>
    )
  }

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <div className="chat-header-left">
          <div className="conversation-tabs">
            {patients.map((patient) => (
              <div className={`conversation-tab ${selectedId === patient.id ? 'is-active' : ''}`} key={patient.id}>
                <button
                  className="conversation-tab-main"
                  type="button"
                  title={patient.name}
                  onClick={() => selectPatient(patient.id)}
                >
                  <span className="conversation-tab-label">{patient.name}问诊</span>
                </button>
                <button
                  className="conversation-tab-close"
                  type="button"
                  aria-label={`关闭${patient.name}对话窗口`}
                  disabled={patients.length <= 1}
                  onClick={() => removePatient(patient.id)}
                >
                  <CloseIcon />
                </button>
              </div>
            ))}
          </div>
          <button
            className="conversation-add-btn"
            type="button"
            onClick={() => message.info('Demo 阶段：请复制新患者文件夹到 TempData/patients 后刷新')}
          >
            <AddIcon />
          </button>
        </div>
        <label className="switch-wrap">
          <span>思考过程</span>
          <input type="checkbox" checked={showThinking} onChange={(e) => setShowThinking(e.target.checked)} />
          <span className={`switch-track ${showThinking ? 'is-on' : ''}`} aria-hidden="true" />
        </label>
      </div>
      {/* 就诊时间选择条 */}
      {encounterList.length > 1 && (
        <div className="encounter-selector">
          <span className="encounter-selector__label">就诊范围：</span>
          <div className="encounter-selector__chips">
            <button
              className={`encounter-chip ${selectedEncounter === null ? 'is-active' : ''}`}
              type="button"
              onClick={() => handleSelectEncounter(null)}
            >
              全部就诊
            </button>
            {encounterList.map((enc) => {
              const isActive =
                selectedEncounter !== null &&
                selectedEncounter.admission === enc.admission
              return (
                <button
                  className={`encounter-chip ${isActive ? 'is-active' : ''}`}
                  key={enc.index}
                  type="button"
                  onClick={() =>
                    handleSelectEncounter({
                      admission: enc.admission,
                      discharge: enc.discharge,
                      type: enc.type,
                      label: enc.label,
                      source_admission: enc.source_admission,
                    })
                  }
                >
                  {enc.label}
                </button>
              )
            })}
          </div>
        </div>
      )}
      <MessageList messages={messages} showThinking={showThinking} />
      <div className="quick-actions-bar">
        <button
          className="quick-action-btn"
          type="button"
          disabled={isStreaming}
          onClick={() => sendMessage('请分析该患者的检查资料')}
        >
          文件分析
        </button>
        <button
          className="quick-action-btn quick-action-btn--primary"
          type="button"
          disabled={isStreaming}
          onClick={handleGenerateReport}
        >
          生成报告
        </button>
      </div>
      <ChatInput onSend={sendMessage} disabled={isStreaming} />
    </div>
  )
}
