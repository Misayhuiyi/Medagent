import { useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import { usePatientStore, useChatStore } from '../../store'
import { fetchChatHistory } from '../../services/api'
import { useChat } from '../../hooks/useChat'
import MessageList from './MessageList'
import ChatInput from './ChatInput'

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

export default function ChatPanel() {
  const selectedId = usePatientStore((s) => s.selectedId)
  const patients = usePatientStore((s) => s.patients)
  const selectPatient = usePatientStore((s) => s.selectPatient)
  const removePatient = usePatientStore((s) => s.removePatient)
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const addMessages = useChatStore((s) => s.addMessages)
  const clearMessages = useChatStore((s) => s.clearMessages)
  const setThinkingTime = useChatStore((s) => s.setThinkingTime)
  const { sendMessage, abort } = useChat(selectedId)
  const [showThinking, setShowThinking] = useState(true)

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
      <MessageList messages={messages} showThinking={showThinking} />
      <ChatInput onSend={sendMessage} disabled={isStreaming} />
    </div>
  )
}
