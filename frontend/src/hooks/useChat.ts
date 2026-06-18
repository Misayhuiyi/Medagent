import { useCallback, useRef } from 'react'
import { useChatStore, useReportStore } from '../store'
import { parseSSE } from '../services/api'
import type { SSEEvent, TabName } from '../types'

export function useChat(patientId: string | null) {
  const abortRef = useRef<AbortController | null>(null)
  const modeRef = useRef<'chat' | 'report'>('chat')

  const addMessage = useChatStore((s) => s.addMessage)
  const appendToLastMessage = useChatStore((s) => s.appendToLastMessage)
  const appendReasoning = useChatStore((s) => s.appendReasoning)
  const setStreaming = useChatStore((s) => s.setStreaming)
  const setLastEventId = useChatStore((s) => s.setLastEventId)
  const setTabData = useReportStore((s) => s.setTabData)

  const abort = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    if (useChatStore.getState().isStreaming) {
      setStreaming(false)
    }
  }, [setStreaming])

  const sendMessage = useCallback(async (content: string, mode: 'chat' | 'report' | 'auto' = 'auto') => {
    if (!patientId) return

    abort()

    const controller = new AbortController()
    abortRef.current = controller

    addMessage({ role: 'user', content, timestamp: new Date().toISOString() })
    setStreaming(true)

    try {
      const lastId = useChatStore.getState().lastEventId
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (lastId) headers['Last-Event-ID'] = String(lastId)

      const response = await fetch(`/api/chat/${encodeURIComponent(patientId)}/messages`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message: content, mode }),
        signal: controller.signal,
      })

      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      if (!response.body) throw new Error('No response body')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const { remaining, events } = parseSSE(buffer)
        buffer = remaining

        for (const event of events) {
          handleEvent(event)
        }
      }

      if (buffer.trim()) {
        const { events } = parseSSE(buffer + '\n\n')
        for (const event of events) {
          handleEvent(event)
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      try { controller.abort() } catch { /* already aborted */ }
      console.error('SSE error:', err)
      addMessage({
        role: 'status',
        content: '连接失败，请重试',
        timestamp: new Date().toISOString(),
      })
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }, [patientId, abort, addMessage, setStreaming])

  function handleEvent(event: SSEEvent) {
    if (event.id) setLastEventId(event.id)

    switch (event.type) {
      case 'status':
        addMessage({
          role: 'status',
          content: getStatusText(event.data.state || ''),
          timestamp: new Date().toISOString(),
        })
        // 报告模式: 在状态消息后追加助手占位提示
        if (modeRef.current === 'report') {
          addMessage({
            role: 'assistant',
            content: '正在分析中，请稍候…',
            timestamp: new Date().toISOString(),
            isPlaceholder: true,
          } as any)
        }
        break
      case 'mode':
        modeRef.current = event.data.mode as 'chat' | 'report'
        break
      case 'reasoning':
        appendReasoning(event.data.content || '')
        break
      case 'token':
        appendToLastMessage(event.data.content || '')
        break
      case 'tab_ready': {
        const tab = event.data.tab as TabName
        setTabData(tab, event.data.data)
        break
      }
      case 'error':
        addMessage({
          role: 'status',
          content: `分析出错：${event.data.message || '未知错误'}`,
          timestamp: new Date().toISOString(),
        })
        break
      case 'done':
        setStreaming(false)
        break
    }
  }

  const generateReport = useCallback((content: string): Promise<void> => sendMessage(content, 'report'), [sendMessage])

  return { sendMessage, generateReport, abort }
}

function getStatusText(state: string): string {
  const map: Record<string, string> = {
    reading_files: '正在读取报告文件...',
    mock_mode: '演示模式',
  }
  return map[state] || state
}
