# 上传患者资料与 PDF 处理完善执行方案

更新时间：2026-07-07

## 一、目标

在保持当前项目 UI 风格、页面结构和核心业务架构不做无关重构的前提下，完善“上传患者资料”能力，使前端可上传患者资料文件，后端可完成 PDF 解析、OCR/文本提取、结构化处理、缓存与存储，并将处理后的资料接入现有分段报告生成、前端预览和 PDF 导出流程。

本方案同时覆盖报告生成速度优化、前端报告展示混乱修复、疗效检测曲线与图表渲染优化，并对齐 `old_MedAgent` 中成熟实现。

## 二、当前项目现状排查范围

### 1. 前端上传入口

当前文件：

- `frontend/src/components/PatientList/AddPatientButton.tsx`

现状：

- 仅显示 Demo 提示：“请直接将患者文件夹复制到 TempData/patients/ 目录”。
- 未真正打开文件选择器。
- 未调用上传接口。
- 未显示上传进度、OCR 进度、失败状态或重试入口。

### 2. 前端接口层

当前文件：

- `frontend/src/services/api.ts`

需要补齐：

- `uploadPatientFiles(files, patientId?)`
- `fetchOcrJobs(patientId)`
- `retryOcrJob(patientId, filename)`
- 上传返回类型、OCR job 类型、错误类型。

### 3. 后端患者文件接口

当前文件：

- `Code/DataCode/web_routes/patients.py`

现状：

- 已有 `/api/patients/upload`，但只保存文件。
- 未启动 OCR 或文本提取。
- 未写入 OCR 状态。
- 未做 sha256 去重。
- 未生成结构化元数据。
- 未提供 `/ocr-jobs` 查询接口。
- 上传后的资料不能稳定进入报告生成链路。

### 4. PDF/OCR 工具

当前文件：

- `Code/DataCode/pdf_ocr.py`
- `Code/DataCode/scripts/batch_pdf_to_md.py`
- `Code/DataCode/builtin_tools.py`

现状：

- 项目内已有 PDF/OCR 工具能力。
- 但与前端上传、后台任务、状态轮询、报告生成入口未形成完整闭环。

### 5. 报告生成链路

重点文件：

- `Code/DataCode/report_context.py`
- `Code/DataCode/skill_executor.py`
- `Code/DataCode/web_routes/chat.py`
- `Code/DataCode/web_routes/reports.py`

需要确认：

- 上传后生成的 OCR Markdown 是否能被 `load_cumulative_patient_files()` 读取。
- 时间分段是否能识别新上传资料。
- 上一期报告上下文是否继续有效。
- 报告生成失败是否不会污染下一期上下文。

### 6. 前端报告渲染与图表

重点文件：

- `frontend/src/components/ReportPanel/*`
- `frontend/src/components/ReportPanel/chartData.ts`
- `frontend/src/components/common/MarkdownRenderer.tsx`

需要重点修复：

- 疗效检测曲线。
- 肿瘤大小趋势。
- 折线图尺寸与 tooltip。
- 图例、坐标轴、单位。
- 时间线排序。
- Markdown/HTML 表格渲染。
- 红/蓝/绿颜色标注。
- 前端预览与 PDF 导出一致性。

## 三、需要重点阅读的 Plan 与规划文档

### 1. `任务需求与执行规划.md`

重点内容：

- 输入来源是患者 PDF 文件。
- PDF 是正式输入格式。
- PDF 需在预处理阶段转换为 Markdown 供 Agent 读取。
- 流程为：患者 PDF → pdf-ocr → 资料整理 → 预处理 → 场景判断 → 病史/概况/方案/预测/建议 → 报告生成。
- 前端需保留现有体验。

### 2. `阶段二详细方案.md`

重点内容：

- `02-data-preprocessing` 包含 `folder-management`、`patient-check`、`pdf-conversion`。
- 需支持损坏 PDF、空文件夹、知识库缺失等异常输入。
- 张三/李四/王五等多患者测试是验收重点。

### 3. `新旧项目对比.md`

重点内容：

- oldmedagent 有成熟上传、OCR、报告预览、图表和 PDF 导出逻辑。
- 新项目新增 V4 模板、知识库、时间分段与连续报告，但上传处理迁移不完整。

### 4. `project_memory.md`

重点内容：

- 记录最近修复约束。
- PDF 导出已向 Playwright 对齐。
- 时间分段和连续报告逻辑已存在。
- 后续修复应避免破坏现有 UI 与核心架构。

## 四、old_MedAgent 对比参考模块

### 1. 前端上传

参考文件：

- `old_MedAgent/frontend/src/components/PatientList/AddPatientButton.tsx`
- `old_MedAgent/frontend/src/components/PatientList/index.tsx`
- `old_MedAgent/frontend/src/services/api.ts`

可复用点：

- 隐藏文件输入。
- 支持文件夹上传 `webkitdirectory`。
- 上传中禁用按钮。
- 上传完成后显示 OCR 处理中状态。
- 轮询 `/ocr-jobs`。
- OCR 完成后刷新患者列表。
- 失败时提示可重试。

### 2. 后端上传与 OCR

参考文件：

- `old_MedAgent/Code/DataCode/web_routes/patients.py`

可复用点：

- 文件路径安全处理。
- 文件分类。
- 日期识别。
- sha256 去重。
- 唯一文件名生成。
- OCR 状态文件。
- 后台 OCR job。
- MinerU 调用。
- 电子 PDF 文本抽取兜底。
- OCR 失败重试。
- `/ocr-jobs` 状态查询。

### 3. 前端图表

参考文件：

- `old_MedAgent/frontend/src/components/ReportPanel/TabHistory.tsx`
- `old_MedAgent/frontend/src/components/ReportPanel/TabPrediction.tsx`
- `old_MedAgent/frontend/src/components/common/EChart.tsx`

可复用点：

- 图表数据长度校验。
- 空数据不渲染空图。
- ECharts 容器稳定尺寸。
- tooltip、legend、坐标轴、单位完整。
- 组件卸载时 dispose。

### 4. PDF 导出

参考文件：

- `old_MedAgent/Code/DataCode/report_generator.py`

可复用点：

- HTML 单源。
- Playwright Chromium PDF。
- A4 页面。
- 打印背景。
- 页边距 `12mm/10mm`。
- 表格分页约束。
- 红/蓝/绿颜色标注。

## 五、前端改造方案

### 1. `AddPatientButton.tsx`

改造目标：

- 从 Demo 提示改为真实上传。
- 保持当前左侧栏加号按钮视觉不变。

实现内容：

- 增加隐藏文件输入：

```tsx
<input type="file" multiple webkitdirectory />
```

- 点击加号触发文件选择。
- 支持文件夹上传和多文件上传。
- 上传中禁用按钮。
- 调用 `uploadPatientFiles(files)`。
- 上传成功后根据 `ocr_jobs` 判断是否进入轮询。
- OCR 完成后刷新患者列表。

### 2. `services/api.ts`

新增或补齐：

```ts
uploadPatientFiles(files: File[], patientId?: string)
fetchOcrJobs(patientId: string)
retryOcrJob(patientId: string, filename: string)
```

上传返回类型：

```ts
interface UploadResult {
  patient_id: string
  files_saved: number
  files: string[]
  duplicates?: string[]
  errors?: Array<{ file: string; error: string }>
  ocr_jobs?: string[]
}
```

OCR job 类型：

```ts
interface OcrJob {
  file?: string
  filename?: string
  status: string
  message?: string
  error?: string
  started_at?: string
  finished_at?: string
  progress?: number
}
```

### 3. `PatientList/index.tsx`

新增内容：

- 上传处理中卡片。
- OCR 状态展示。
- 文件树状态标识：
  - 已识别
  - 识别中
  - 待识别
  - 识别失败
  - 文本兜底

保持不变：

- 左侧栏布局。
- 当前文件树视觉风格。
- 患者选择交互。

### 4. `patientStore.ts`

新增状态：

- `uploadProcessing`
- `ocrJobs`
- `selectedUploadedPatient`

用途：

- 防止切换页面后上传状态丢失。
- OCR 完成后自动刷新患者列表。

### 5. `ChatPanel/index.tsx`

PDF 预览策略：

- 有 OCR Markdown：显示 OCR 内容。
- OCR 识别中：显示处理状态。
- OCR 失败：显示失败原因和重试入口。
- 原 PDF 可预览时：保留 iframe/Blob URL 预览。

## 六、后端改造方案

### 1. 新增 `document_processing.py`

建议职责：

- 文件分类。
- 日期识别。
- PDF hash 去重。
- PDF 文本抽取。
- OCR 调度。
- OCR Markdown 写入。
- 元数据生成。
- 上传处理结果封装。

### 2. 新增 `ocr_jobs.py`

建议职责：

- 内存 job 表。
- OCR 状态文件读写。
- 并发限制。
- stale job 修复。
- OCR 重试。
- OCR job 查询。

### 3. 新增 `pdf_text_extractor.py`

建议职责：

- 电子 PDF 快速文本抽取。
- 扫描 PDF 判断。
- 页数统计。
- 文本质量评估。
- OCR 兜底策略。

### 4. 修改 `web_routes/patients.py`

#### `POST /api/patients/upload`

升级流程：

1. 校验文件类型、大小、数量。
2. 解析 `webkitRelativePath`。
3. 推断 `patient_id`。
4. 分类文件。
5. 保存原始 PDF。
6. 计算 sha256。
7. 重复文件复用 OCR。
8. 启动后台 OCR/text extraction job。
9. 返回 `ocr_jobs`。

#### `GET /api/patients/{patient_id}/ocr-jobs`

返回：

- 文件名
- 状态
- 进度
- 错误信息
- 开始时间
- 完成时间

#### `POST /api/patients/{patient_id}/files/{filename}/ocr/retry`

用途：

- 对失败或待识别 PDF 重新启动 OCR。

#### `GET /api/patients/{patient_id}/files`

增加字段：

- `ocr_status`
- `ocr_message`
- `encounter_date`
- `category`
- `has_ocr`
- `hash`
- `text_quality`

#### `GET /api/patients/{patient_id}/files/{filename}`

策略：

- PDF 有 OCR：返回 OCR Markdown。
- PDF 正在识别：返回业务状态。
- PDF 识别失败：返回失败信息。
- 非 PDF：直接读取文本。

## 七、PDF 解析、OCR 与结构化处理设计

### 1. 处理顺序

```text
保存原始 PDF
  ↓
计算 sha256
  ↓
查找缓存
  ↓
电子 PDF 快速文本抽取
  ↓
若文本不足或乱码，进入 OCR
  ↓
生成 OCR Markdown
  ↓
写入 status.json / meta.json
  ↓
刷新患者时间分段
```

### 2. 存储目录

建议结构：

```text
TempData/patients/{patient_id}/
  影像报告/
    2025-07-17_CT_胸部.pdf
    2025-07-17_CT_胸部/
      ocr/
        2025-07-17_CT_胸部.md
        status.json
      meta.json
```

### 3. `meta.json` 建议字段

```json
{
  "source_pdf": "影像报告/2025-07-17_CT_胸部.pdf",
  "sha256": "...",
  "document_type": "影像报告",
  "document_date": "2025-07-17",
  "visit_date": "",
  "admission_date": "",
  "discharge_date": "",
  "page_count": 3,
  "text_length": 4500,
  "text_quality": "ok",
  "extractor": "pdf-text|mineru|easyocr|fallback",
  "created_at": "2026-07-07T..."
}
```

### 4. OCR 状态文件

`status.json` 示例：

```json
{
  "status": "success",
  "message": "已完成 OCR",
  "job_id": "ocr_...",
  "started_at": "...",
  "finished_at": "...",
  "extractor": "mineru",
  "sha256": "..."
}
```

状态枚举：

- `pending`
- `running`
- `success`
- `failed`
- `reused`
- `fallback_text`

## 八、报告生成速度优化策略

### 1. 增量 OCR

- 上传时计算 sha256。
- 同 hash 文件直接复用已有 OCR。
- 不重复处理历史文件。

### 2. 电子 PDF 快速通道

- 先尝试文本抽取。
- 可抽取足够文本则跳过 OCR。
- 扫描件再进入 OCR。

### 3. 上传后后台预处理

- 上传完成即进入 OCR 队列。
- 用户点击“生成报告”时不再临时转换 PDF。

### 4. 报告生成前资料状态检查

如果存在未完成 OCR：

- 前端提示“部分资料仍在识别”。
- 允许用户选择等待或使用已完成资料生成。

### 5. 知识库检索缓存

- 缓存 key：

```text
patient_id + visit_date + report_step + query_hash + kb_version
```

- 默认使用快速向量召回。
- reranker 作为可选开关。

### 6. 模型调用优化

- 保持报告生成温度为 0。
- 避免重复注入同一 OCR 全文。
- 先做患者资料摘要，再分步骤调用。
- 失败 tab 不写入成功报告。

### 7. 图表数据本地提取

肿瘤大小、日期、RECIST、肿瘤标志物等优先用规则提取，减少 LLM 编造图表数据。

### 8. PDF 导出缓存

缓存 key：

```text
report_json_hash + template_version + patient_info_hash
```

报告未变时直接返回缓存 PDF。

## 九、前端报告图表与疗效曲线修复策略

### 1. 统一图表数据结构

```ts
interface ClinicalChartData {
  labels: string[]
  values: number[]
  unit: 'mm' | '%' | 'ng/ml' | ''
  points: Array<{
    date: string
    value: number
    source: string
    note?: string
    missing?: boolean
  }>
  trend_text: string
  baseline?: number
  latest?: number
  change_abs?: number
  change_pct?: number
}
```

### 2. `chartData.ts`

负责：

- 日期排序。
- 数值转换。
- `cm` 转 `mm`。
- 缺失值处理。
- 重复日期合并。
- 异常值标记。
- 生成趋势说明。

### 3. `TabHistory.tsx`

修复：

- 肿瘤大小趋势图。
- 空数据说明。
- 时间线按日期排序。
- 节点颜色与 V4 标注一致。

### 4. `TabPrediction.tsx`

修复：

- 疗效预测曲线。
- PFS/OS 曲线。
- 不良反应预测曲线。
- tooltip、legend、单位、坐标轴。
- 缺失值不渲染空图。

### 5. 公共 EChart 组件

要求：

- 稳定高度。
- ResizeObserver。
- unmount 时 dispose。
- 选项更新不残留旧曲线。

### 6. PDF 导出一致性

后端导出不能依赖前端 canvas。

策略：

- 前端用 ECharts。
- 后端用同一结构化数据生成 SVG。
- V4 HTML/PDF 与前端显示同源数据。

## 十、数据流转设计

```text
前端上传文件/文件夹
  ↓
POST /api/patients/upload
  ↓
保存原始 PDF + 分类 + 日期识别 + sha256 去重
  ↓
后台 OCR / 文本抽取
  ↓
生成 OCR Markdown + meta.json + status.json
  ↓
刷新患者列表与就诊时间分段
  ↓
用户点击生成报告
  ↓
load_cumulative_patient_files 读取当前时间段 OCR
  ↓
collect_prior_context_entries 注入上一期报告
  ↓
知识库检索
  ↓
05-09 报告页签生成
  ↓
保存 report.json / report.md
  ↓
前端五标签页预览
  ↓
V4 HTML 渲染
  ↓
Playwright PDF 导出
```

## 十一、异常处理方案

### 1. 上传失败

处理：

- 返回文件级错误。
- 不影响其他文件。
- 前端提示“部分文件上传失败”。

### 2. PDF 损坏

处理：

- 写入 `status=failed`。
- message 为“PDF 损坏或无法打开”。
- 文件列表显示失败。

### 3. OCR 失败

处理：

- 尝试电子 PDF 文本抽取兜底。
- 兜底失败则标记失败。
- 提供重试按钮。

### 4. 资料为空

处理：

- 禁止生成报告。
- 前端提示“暂无可用 OCR 资料”。

### 5. 资料过大

处理：

- 限制单文件大小和总大小。
- 后台分批处理。
- 前端显示队列进度。

### 6. 重复上传

处理：

- sha256 命中则复用 OCR。
- 前端提示“已复用历史识别结果”。

### 7. LLM 调用失败

处理：

- 不写入成功报告。
- 不进入上一期报告上下文。
- 前端提供重试。

### 8. 图表数据缺失

处理：

- 不渲染空图。
- 显示“暂无可量化数据”。
- PDF 中同样显示文字说明。

### 9. OCR 任务中断

处理：

- 服务启动时扫描 `running` 且超时的状态。
- 自动改为 `pending` 或 `failed_retryable`。

## 十二、测试与验收方案

### 1. 单元测试

覆盖：

- 文件名日期解析。
- 文档类型分类。
- sha256 去重。
- OCR status 读写。
- PDF 文本抽取兜底。
- chart data normalization。
- Markdown 清洗。

### 2. 接口测试

覆盖：

- 上传单 PDF。
- 上传文件夹。
- 重复上传。
- 损坏 PDF。
- 查询 OCR jobs。
- OCR retry。
- 文件列表状态。
- 生成报告。
- 下载 HTML/PDF。

### 3. 端到端测试

流程：

1. 上传新患者文件夹。
2. 等待 OCR 完成。
3. 患者列表出现新患者。
4. 文件树显示 PDF 与 OCR 状态。
5. 点击生成报告。
6. 五标签页显示完整内容。
7. 图表、曲线、时间线正常。
8. 下载 PDF。
9. PDF 文件头为 `%PDF`。
10. PDF 内容与前端预览一致。

### 4. 性能测试

场景：

- 1 个 PDF。
- 20 个 PDF。
- 100 个 PDF。
- 重复上传 100 个 PDF。
- OCR 已缓存。
- PDF 首次导出。
- PDF 二次导出。

指标：

- 上传接口响应时间。
- OCR 总耗时。
- 生成报告耗时。
- 知识库检索耗时。
- PDF 导出耗时。
- 前端渲染耗时。

### 5. 前端展示验证

检查：

- 上传按钮状态。
- OCR 处理中卡片。
- 文件树状态。
- 报告标签页。
- Markdown 表格。
- 疗效检测曲线。
- 肿瘤趋势图。
- tooltip。
- 图例。
- 坐标轴。
- 单位。
- 颜色标注。

### 6. PDF 导出验证

检查：

- Playwright 是否命中。
- 文件头 `%PDF`。
- 基础信息完整。
- 表格不截断。
- 标题不与正文分离。
- 图表不跨页。
- 中文字体正常。
- 前端预览与 PDF 内容一致。

## 十三、分阶段实施计划

### P0：上传与 OCR 闭环

优先级：最高

改动：

- 迁移 oldmedagent 上传按钮逻辑。
- 完善 `/api/patients/upload`。
- 增加 `/ocr-jobs`。
- 增加 OCR 状态文件。
- 上传后自动刷新患者列表。

产出：

- 前端可上传 PDF/文件夹。
- 后端可保存、识别、返回状态。
- 上传资料可出现在患者列表中。

风险：

- OCR 环境不稳定。

回滚：

- 保留直接复制到 `TempData/patients` 的兼容路径。

### P1：上传资料进入报告生成

优先级：高

改动：

- 上传后生成规范 OCR Markdown。
- 刷新时间分段。
- 接入 `load_cumulative_patient_files()`。
- 生成报告前检查 OCR 完成度。

产出：

- 上传资料可直接用于报告生成。

风险：

- 时间字段不规范导致分段错误。

回滚：

- 未识别时间的资料归入“未分类/最新资料”，仍可生成综合报告。

### P2：报告速度优化

优先级：高

改动：

- sha256 去重。
- 电子 PDF 快速文本抽取。
- OCR 缓存。
- 知识库检索缓存。
- PDF 导出缓存。

产出：

- 重复上传和重复生成明显提速。

风险：

- 缓存 key 不唯一导致复用错误。

回滚：

- 增加强制刷新参数。
- 生成报告前可清理患者缓存。

### P3：前端图表与报告可读性修复

优先级：中高

改动：

- 统一 chart data。
- 修复疗效检测曲线。
- 修复时间线。
- 修复 Markdown 表格。
- 修复颜色标注。
- 增加趋势文本。

产出：

- 前端报告更清晰。
- PDF 与预览一致性提升。

风险：

- 旧报告字段格式多样。

回滚：

- 保留旧字段兼容层。

### P4：持久化队列与 SAG 增量索引

优先级：后续优化

改动：

- OCR job 持久化。
- 服务重启恢复。
- 上传资料生成 event/entity 索引。
- 接入 SAG 多跳检索。

产出：

- 大批量资料处理更稳。
- 后续推理质量更高。

风险：

- 范围较大，容易引入无关重构。

回滚：

- 保持当前 RAG/ChromaDB 路径。

## 十四、优先级结论

### 必须优先完成

1. 前端上传按钮真实可用。
2. 后端上传后自动保存、去重、OCR/文本提取。
3. OCR 状态查询与前端轮询。
4. 上传资料进入现有报告生成流程。
5. 上传后生成的报告可正常预览和导出 PDF。

### 第二优先级

1. 图表数据结构统一。
2. 疗效检测曲线和肿瘤趋势图修复。
3. Markdown/HTML 表格和时间线稳定渲染。
4. 报告生成速度优化。

### 后续优化

1. OCR 队列持久化。
2. PDF 导出缓存。
3. 患者资料 SAG/event/entity 增量索引。
4. 更细粒度的性能监控面板。

