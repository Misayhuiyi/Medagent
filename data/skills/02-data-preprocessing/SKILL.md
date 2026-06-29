---
name: 02-data-preprocessing
description: 验证和整理患者资料内容，按需执行 PDF→MD 转换，为后续AI问诊做准备。
version: 1.2.0
开发者: Steven Agent
changelog: |
  1.2.0 (2026-06-23): 增加双路径逻辑——OCR文件已存在则直接验证使用，不存在则调用pdf-conversion提取PDF文本
---

# 资料预处理

肺癌医生Agent应用层的第二个执行步骤。负责验证患者资料完整性，按需执行 PDF→MD 文本提取，整理文件清单，为后续步骤提供结构化的数据概览。

## ⚠️ 启动前必读：OCR 状态判断（最高优先级）

在执行任何操作前，必须先检查 `files` 参数内容：

**如果 `files` 中包含 `## ⚠️ OCR 状态：已完成` 标记，或包含 `### 文件 N:` 格式的内容块（N 为数字），说明 OCR 已就绪 → 直接走路径 A，禁止调用 PDF 转换工具。**

只有 `files` 为 `（无可用患者文件）` 或完全为空时，才能走路径 B。

**双路径模式**：
- **路径 A（OCR 已就绪 — 当前状态）**：`files` 参数中已包含提取后的文本内容 → 直接验证完整性，跳过 PDF 转换，禁止调用 `batch_pdf_to_md` 或 `skills/pdf-conversion/SKILL.md`
- **路径 B（OCR 未就绪）**：`files` 参数为空或无有效内容 → 扫描患者 PDF 目录，调用 pdf-conversion 子 Skill 提取文本

## 执行流程

### 1、标准的输入

（1）`files`：患者资料文件列表及文本内容。Pipeline 模式下由 `_load_patient_files()` 从 `TempData/patients/{patient_id}/**/ocr/*.md` 预加载。格式为文本块（Markdown），含文件名和正文。
（2）`patient_id`：患者ID（如 "张三-001"）
（3）`visit_date`：就诊日期
（4）`previous_results`：前序步骤的输出

### 2、步骤说明

**⚠️ 步骤 0（最高优先级，必须先执行）：判断 OCR 文件是否已就绪**

在执行其他任何步骤之前，先检查 `files` 参数中的内容：

**情况 A：files 中有有效文件内容**（如包含"### 文件"开头的文本块、"OCR 状态：已完成"标记，或文件数量 > 0）
→ OCR 文件已由上游预加载，**跳过 PDF 转换**，直接进入步骤 1。
→ **禁止调用 `batch_pdf_to_md` 工具或 `sessions_spawn` 到 `skills/pdf-conversion/SKILL.md`**。
→ 这是当前状态：OCR 已完成 ✓

**情况 B：files 为空或无有效内容**（内容为"无可用患者文件"或文件数量为 0）
→ OCR 文件未就绪，需要提取 PDF 文本。进入步骤 2B。

#### 步骤1：检查患者是否已使用过AI医生

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/patient-check/SKILL.md`：
- 根据患者姓名、门诊号查询患者—AI医生对应关系表
- 判断患者是否已使用过AI医生
- 输出：检查结果（新患者/老患者）+ 已有患者信息（如存在）

#### 步骤2：根据检查结果执行分支操作

**分支A：新患者（未使用过AI医生）**

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/folder-management/SKILL.md` 子流程A：
- 填写患者信息表（姓名、门诊号、性别、年龄、就诊时间）
- 创建患者主文件夹：`本地患者库/{患者姓名}_{门诊号}/`
- 创建首个就诊时间文件夹及5种资料类型子文件夹
- 将患者信息写入 `患者信息.json`
- 输出：本地患者库路径、患者信息JSON

**分支B：老患者（已使用过AI医生）**

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/folder-management/SKILL.md` 子流程B：
- 查找现有患者文件夹路径
- 更新患者信息表（新增就诊时间）
- 创建新就诊时间文件夹及5种资料类型子文件夹
- 输出：本地患者库路径、患者信息JSON

#### 步骤2（OCR 就绪时跳过步骤3-4，直接到验证）

（当前场景：OCR 已在 步骤0 确认为就绪 → 跳过本步骤及步骤3-4）

#### 步骤3：提取 PDF 文本（仅当 OCR 未就绪时执行）

仅在 步骤0 判定为**情况 B**（OCR 未就绪）时执行。

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/pdf-conversion/SKILL.md`：
- 传入患者资料目录路径：`TempData/patients/{patient_id}/`
- 子 Skill 自动扫描目录下所有 PDF 文件，使用 `batch_pdf_to_md` 工具批量转换为 MD
- 转换后的 MD 文件输出到各 PDF 同级目录的 `ocr/` 子文件夹

#### 步骤4：验证已有资料内容

- 检查文件数量是否与预期一致（各资料类型下至少应有文件）
- 检查文件内容非空
- 如有缺失的资料类型，在输出中注明
- **当前状态（OCR 已就绪）**：直接验证 `files` 中预加载的内容，无需额外操作

#### 步骤5：输出汇总

- 汇总本地患者库路径、患者信息、文件清单
- 输出到标准输出，供下一个Skill（循环次数确定）使用

### 3、条件判断

| 条件 | 处理方式 |
|------|----------|
| 患者从未使用过AI医生 | 走分支A（新患者流程） |
| 患者已使用过AI医生 | 走分支B（老患者流程） |
| `files` 中已有有效文件内容 | 走路径 A：跳过 PDF 转换，直接验证 |
| `files` 为空或无有效内容 | 走路径 B：调用 pdf-conversion 提取 PDF 文本 |
| 患者信息中缺少必要字段 | 提示用户补充完整信息 |

### 4、错误处理

| 错误类型 | 处理方案 |
|----------|----------|
| 患者—AI医生对应关系表不存在 | 按新患者处理，创建对应关系表 |
| 患者文件夹已存但无对应关系记录 | 按老患者处理，修复对应关系表 |
| 资料内容为空（路径A） | 标记缺失，在输出中注明 |
| 患者 PDF 目录不存在或无 PDF 文件（路径B） | 标记「无可转换 PDF」，在输出中注明 |
| PDF 转换失败 | 记录失败文件列表，已成功转换的继续使用 |

### 5、规范的输出

（1）本地患者库路径（字符串）
（2）患者信息JSON（含姓名、门诊号、性别、年龄、就诊时间列表）
（3）资料文件清单（数组，含文件路径和内容摘要）
（4）转换状态标记（"ocr_preloaded" / "ocr_extracted" / "no_files_available"）
（5）预处理日志（记录所有操作和异常情况）
