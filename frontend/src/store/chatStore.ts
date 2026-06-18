import { create } from 'zustand'
import type { ChatMessage } from '../types'

interface ChatState {
  messages: ChatMessage[]
  isStreaming: boolean
  lastEventId: number | undefined
  thinkingTime: number
  addMessage: (message: ChatMessage) => void
  addMessages: (messages: ChatMessage[]) => void
  appendToLastMessage: (content: string) => void
  appendReasoning: (content: string) => void
  setStreaming: (streaming: boolean) => void
  setThinkingTime: (t: number) => void
  setLastEventId: (id: number | undefined) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isStreaming: false,
  lastEventId: undefined,
  thinkingTime: 0,

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  addMessages: (messages) =>
    set((state) => ({ messages: [...state.messages, ...messages] })),

  appendToLastMessage: (content) =>
    set((state) => {
      const msgs = [...state.messages]
      const last = msgs[msgs.length - 1]
      if (last && last.role === 'assistant') {
        if ((last as any).isPlaceholder) {
          msgs[msgs.length - 1] = { ...last, content, isPlaceholder: false } as any
        } else {
          msgs[msgs.length - 1] = { ...last, content: last.content + content }
        }
      } else {
        msgs.push({ role: 'assistant', content, timestamp: new Date().toISOString() })
      }
      return { messages: msgs }
    }),

  appendReasoning: (content) =>
    set((state) => {
      const msgs = [...state.messages]
      const last = msgs[msgs.length - 1]
      if (last && last.role === 'assistant') {
        msgs[msgs.length - 1] = { ...last, reasoning: (last.reasoning || '') + content }
      } else {
        msgs.push({ role: 'assistant', content: '', reasoning: content, timestamp: new Date().toISOString() })
      }
      return { messages: msgs }
    }),

  setStreaming: (streaming) => set({ isStreaming: streaming }),
  setThinkingTime: (t) => set({ thinkingTime: t }),
  setLastEventId: (id) => set({ lastEventId: id }),
  clearMessages: () => set({ messages: [], isStreaming: false, lastEventId: undefined, thinkingTime: 0 }),
}))
