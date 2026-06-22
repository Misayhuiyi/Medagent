import { create } from 'zustand'
import type { TabName, ReportData } from '../types'

interface ReportState {
  tabs: Partial<ReportData>
  activeTab: TabName
  tabContents: Partial<Record<TabName, string>>
  setTabData: (tab: TabName, data: unknown) => void
  appendTabContent: (tab: TabName, chunk: string) => void
  setActiveTab: (tab: TabName) => void
  setReportData: (data: Partial<ReportData>) => void
  clearTabs: () => void
}

export const useReportStore = create<ReportState>((set) => ({
  tabs: {},
  tabContents: {},
  activeTab: 'patient-history',

  setTabData: (tab, data) =>
    set((state) => ({ tabs: { ...state.tabs, [tab]: data } })),

  appendTabContent: (tab, chunk) =>
    set((state) => ({
      tabContents: { ...state.tabContents, [tab]: (state.tabContents[tab] || '') + chunk },
    })),

  setActiveTab: (tab) => set({ activeTab: tab }),

  setReportData: (data) => set({ tabs: data }),

  clearTabs: () => set({ tabs: {}, tabContents: {}, activeTab: 'patient-history' }),
}))
