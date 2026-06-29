import { create } from 'zustand'
import type { Patient, PatientFile } from '../types'

export interface EncounterSelection {
  admission: string
  discharge: string
}

interface PatientState {
  patients: Patient[]
  selectedId: string | null
  files: PatientFile[]
  selectedEncounter: EncounterSelection | null  // null = 全部就诊
  setPatients: (patients: Patient[]) => void
  selectPatient: (id: string | null) => void
  removePatient: (id: string) => void
  setFiles: (files: PatientFile[]) => void
  setSelectedEncounter: (encounter: EncounterSelection | null) => void
}

export const usePatientStore = create<PatientState>((set) => ({
  patients: [],
  selectedId: null,
  files: [],
  selectedEncounter: null,
  setPatients: (patients) => set((state) => {
    const autoSelect = state.selectedId == null && patients.length > 0
    const selectedStillExists = state.selectedId != null && patients.some((patient) => patient.id === state.selectedId)
    return {
      patients,
      selectedId: autoSelect ? patients[0].id : selectedStillExists ? state.selectedId : patients[0]?.id ?? null,
      files: autoSelect || !selectedStillExists ? [] : state.files,
      selectedEncounter: autoSelect || !selectedStillExists ? null : state.selectedEncounter,
    }
  }),
  selectPatient: (id) => set({ selectedId: id, files: [], selectedEncounter: null }),
  removePatient: (id) => set((state) => {
    const patients = state.patients.filter((patient) => patient.id !== id)
    const removingSelected = state.selectedId === id
    return {
      patients,
      selectedId: removingSelected ? patients[0]?.id ?? null : state.selectedId,
      files: removingSelected ? [] : state.files,
      selectedEncounter: removingSelected ? null : state.selectedEncounter,
    }
  }),
  setFiles: (files) => set({ files }),
  setSelectedEncounter: (encounter) => set({ selectedEncounter: encounter }),
}))
