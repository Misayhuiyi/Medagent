import { create } from 'zustand'
import type { TabName, ReportData } from '../types'

interface ReportState {
  tabs: Partial<ReportData>
  activeTab: TabName
  setTabData: (tab: TabName, data: unknown) => void
  setActiveTab: (tab: TabName) => void
  setReportData: (data: Partial<ReportData>) => void
  clearTabs: () => void
}

export const useReportStore = create<ReportState>((set) => ({
  tabs: {},
  activeTab: 'patient-history',

  setTabData: (tab, data) =>
    set((state) => ({ tabs: { ...state.tabs, [tab]: data } })),

  setActiveTab: (tab) => set({ activeTab: tab }),

  setReportData: (data) => set({ tabs: data }),

  clearTabs: () => set({ tabs: {}, activeTab: 'patient-history' }),
}))
