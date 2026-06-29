// ── 患者相关 ──

export interface PatientEncounter {
  admission: string
  discharge: string
}

export interface Patient {
  id: string
  name: string
  date: string
  discharge_date?: string
  encounters?: PatientEncounter[]
  file_count: number
  diagnosis?: string
}

export interface PatientFile {
  name: string
  size: number
  type: string
  modified_time: number
  has_ocr?: boolean
}

export interface FileContent {
  name: string
  content: string
}

// ── 聊天相关 ──

export interface ChatMessage {
  role: 'user' | 'assistant' | 'status'
  content: string
  timestamp: string
  reasoning?: string
}

export interface MessageRequest {
  message: string
  mode?: 'chat' | 'report' | 'auto'
  encounter?: EncounterFilter | null
}

export interface EncounterFilter {
  admission: string
  discharge: string
}

// ── SSE 事件（判别联合） ──

export type SSEEvent =
  | { id?: number; type: 'status'; data: StatusData }
  | { id?: number; type: 'mode'; data: ModeData }
  | { id?: number; type: 'reasoning'; data: TokenData }
  | { id?: number; type: 'token'; data: TokenData }
  | { id?: number; type: 'tab_ready'; data: TabReadyData }
  | { id?: number; type: 'tab_content'; data: TabContentData }
  | { id?: number; type: 'error'; data: ErrorData }
  | { id?: number; type: 'done'; data: DoneData }

export interface ModeData {
  mode: 'chat' | 'report'
}

export interface StatusData {
  state: string
}

export interface TokenData {
  content: string
}

export interface TabReadyData {
  tab: TabName
  data: Record<string, unknown>
}

export interface TabContentData {
  tab: TabName
  content: string
}

export interface ErrorData {
  tab?: TabName
  message: string
}

export interface DoneData {
  // empty
}

// ── 报告相关 ──

export type TabName = 'patient-history' | 'patient-overview' | 'treatment-plan' | 'efficacy-prediction' | 'suggestions'

export const TAB_ORDER: TabName[] = ['patient-history', 'patient-overview', 'treatment-plan', 'efficacy-prediction', 'suggestions']

export const TAB_LABELS: Record<TabName, string> = {
  'patient-history': '患者病史',
  'patient-overview': '患者概况',
  'treatment-plan': '治疗方案',
  'efficacy-prediction': '疗效预测',
  'suggestions': '其他建议',
}

export interface ReportData {
  'patient-history'?: HistoryData
  'patient-overview'?: OverviewData
  'treatment-plan'?: TreatmentData
  'efficacy-prediction'?: PredictionData
  'suggestions'?: CareData
}

// ── Tab 1: 患者病史 ──

export interface HistoryData {
  visit_count: number
  visit_type?: { type: number; label: string; rationale: string }
  lesion_numbering?: {
    primary: Array<{ id: string; location: string; first_seen: string }>
    lymph_nodes: Array<{ id: string; location: string; first_seen: string }>
    metastases: Array<{ id: string; location: string; first_seen: string }>
  }
  present_illness: {
    timeline: TimelineItem[]
    tumor_size_chart: ChartData
  }
  past_history: string
  allergy_history: string
  personal_history: string
  family_history: string
  treatment_history?: Array<{
    date: string
    regimen: string
    drugs: string
    best_response: string
    main_ae: string
    stop_reason?: string
  }>
}

export interface TimelineItem {
  date: string
  label: string
  content: string
  color: 'green' | 'blue' | 'red'
  type?: string
  lesion_id?: string
  source?: string
}

// ── Tab 2: 患者概况 ──

export interface OverviewData {
  chief_complaint: string
  physical_examination: string
  auxiliary_examination: {
    imaging: string
    lab_tests: string
  }
  ai_tumor_burden: {
    t_stage: string
    n_stage: string
    m_stage: string
    clinical_stage: string
    conclusion: string
    lesions: LesionItem[]
  }
  ai_efficacy: {
    vs_baseline: EfficacyComparison
    vs_previous: EfficacyComparison
    best_response: EfficacyComparison
  }
  ai_adverse_events: {
    symptoms: string
    signs: string
    imaging: string
    lab_tests: string
    by_system?: Record<string, string>
    conclusion: string
  }
  ai_comorbidity: string
  ecog_score: {
    score: number
    description: string
  }
  supplemental_tests?: string
  diagnosis: {
    tumor: string
    adverse_events: string
    comorbidity: string
  }
}

export interface LesionItem {
  id: string
  location: string
  baseline: number
  current: number
  change: string
}

export interface EfficacyComparison {
  response: string
  change: string
}

// ── Tab 3: 治疗方案 ──

export interface TreatmentData {
  decision_path?: {
    step_a: string
    step_b: string
    step_c: string
    step_d: string
    step_e: string
  }
  treatment_plans: TreatmentPlan[]
  drug_classification?: {
    anti_tumor: string
    ae_management: string
    comorbidity_management: string
  }
  adverse_reaction_plan: string
  comorbidity_plan: string
  clinical_trials: ClinicalTrial[]
}

export interface TreatmentPlan {
  rank: number
  name: string
  strategy: string
  treatment_line?: string
  efficacy_score: number
  adverse_score: number
  prognosis_score: number
  reason: string
  adverse_handling: string
}

export interface ClinicalTrial {
  name: string
  phase: string
  match: boolean
  criteria: string
  local_hospital?: boolean
}

// ── Tab 4: 疗效预测 ──

export interface PredictionData {
  prognostic_factors?: {
    favorable: Array<{ factor: string; citation: string }>
    unfavorable: Array<{ factor: string; citation: string }>
  }
  regimen_predictions?: Array<{
    name: string; orr: string; pfs_median: string; os_median: string
    pfs_12mo: string; os_24mo: string; citation: string
  }>
  tumor_prediction: MultiSeriesChartData
  tumor_marker_trend?: {
    labels: string[]
    markers: Array<{ name: string; unit: string; values: number[]; trend: string }>
  }
  adverse_prediction: AdversePrediction[]
  cross_regimen_comparison?: {
    headers: string[]
    rows: string[][]
  }
  prognosis: PrognosisData
  disclaimer?: string
}

export interface ChartData {
  labels: string[]
  values: number[]
}

export interface MultiSeriesChartData {
  labels: string[]
  series: { name: string; values: number[] }[]
}

export interface AdversePrediction {
  name: string
  labels: string[]
  grade1: number[]
  grade2: number[]
  grade3?: number[]
}

export interface PrognosisData {
  labels: string[]
  pfs: number[]
  os: number[]
}

// ── Tab 5: 人文关怀 ──

export interface CareData {
  psychological_care: string
  clinical_trials?: Array<{
    name: string; phase: string; match: boolean; criteria: string
    local_hospital: boolean; priority: string
  }>
  palliative_care?: {
    pain: string; nutrition: string; psychological: string; respiratory: string
  }
  supportive_measures?: {
    new_drug_exploration: string; adjunctive_medications: string; rehabilitation: string
  }
  health_measures: string
  tcm_suggestions: string
  mdt_recommendations?: Array<{ department: string; rationale: string }>
  patient_education?: {
    smoking?: string; diet: string; exercise: string; compliance: string; follow_up: string
  }
  nursing_care: string
  follow_up_plan?: string
}

// ── 通用 ──

export interface AssessmentColor {
  border: string
  bg: string
  label: string
}

export const ASSESSMENT_COLORS: Record<string, AssessmentColor> = {
  tumor_burden: { border: '#0071e3', bg: '#f0f6ff', label: '肿瘤负荷' },
  efficacy: { border: '#34c759', bg: '#f0faf3', label: '治疗疗效' },
  adverse: { border: '#ff3b30', bg: '#fff5f3', label: '不良反应' },
  other: { border: '#8e8e93', bg: '#f5f5f7', label: 'ECOG/其他' },
}
