---
name: 08-efficacy-prediction
description: 对选定治疗方案进行疗效预测、不良反应预测、全生命周期预后预测并绘图。适用场景：治疗方案确定后需要预测效果时。不适用场景：治疗方案尚未确定时。
version: 1.1.0
开发者: Steven Agent
changelog: |
  1.1.0 (2026-05-30): 接入RAG知识库，预测评分参考指南中的疗效/不良反应/预后数据
---

# 疗效预测

肺癌医生Agent应用层第8个Skill。对选定治疗方案进行多维度预测评估并可视化。

## 执行流程

### 1、输入
（1）06-患者概况的输出
（2）07-治疗方案的输出（选定的治疗方案）
（3）RAG知识库路径：`skills/folder-rag/database/chroma_db`

### 2、步骤说明

三个子步骤互不依赖（各子Skill内部独立完成RAG检索），通过并行子Agent同时执行：

创建子Agent（`sessions_spawn_parallel`，`context="isolated"`）同时调用以下3个子Skill：

```json
[
  "skills/efficacy-prediction-scoring/SKILL.md",
  "skills/adverse-event-prediction/SKILL.md",
  "skills/prognosis-prediction/SKILL.md"
]
```

各子Skill职责（每个内部独立完成RAG知识检索）：
- **skills/efficacy-prediction-scoring/SKILL.md**：内部先RAG检索方案疗效数据，根据患者概况+RAG数据进行疗效预测评分，绘图（横坐标=生存时间，纵坐标=肿瘤大小变化曲线），标注RAG参考数据
- **skills/adverse-event-prediction/SKILL.md**：内部先RAG检索不良反应数据，预测系列不良反应及其概率，绘图（每种不良反应1张图），标注RAG参考发生率
- **skills/prognosis-prediction/SKILL.md**：内部先RAG检索预后数据，预测进展/复发/死亡概率，绘图（横坐标=生存时间，纵坐标=三条概率曲线），标注RAG参考数据

### 3、输出
（1）疗效预测报告（含评分+图表+RAG引用）
（2）不良反应预测报告（含评分+图表+RAG引用）
（3）预后预测报告（含评分+图表+RAG引用）

### 4、图表输出规范

- 禁止输出 ASCII 文本图、字符曲线、`●`、`\`、`│`、`╲`、分号堆叠曲线或代码块图。
- 曲线类内容必须优先输出结构化数据，供前端 ECharts 和 PDF 模板渲染；若无法提供结构化曲线，必须降级为 Markdown 表格，不得用纯文本图替代。
- “各不良反应预测概率（≥Grade 3）”固定表格字段：不良反应、预测概率、风险等级、监测建议、处理建议。
- 肿瘤最大径、KL-6、CEA、CA153、CYFRA、FVC、FEV1、DLCO 等趋势固定表格字段：时间点、指标、数值、单位、变化趋势、临床解释。
- “不良反应严重程度热力图”若无法输出真实矩阵图，必须输出矩阵表：不良反应、各时间点严重程度、等级说明。
- 图表标题、图例、单位、时间点、监测建议和说明文字必须分开输出；单段不超过 120 个中文字符。
- 结构化 JSON 字段建议：
  - `tumor_prediction`: `{ "labels": [], "series": [{ "name": "肿瘤最大径", "values": [] }] }`
  - `tumor_marker_trend`: `{ "labels": [], "markers": [{ "name": "KL-6", "unit": "U/mL", "values": [], "trend": "" }] }`
  - `lung_function_trend`: `{ "labels": [], "markers": [{ "name": "DLCO", "unit": "%pred", "values": [], "trend": "" }] }`
  - `adverse_prediction`: `[{ "name": "", "labels": [], "grade1": [], "grade2": [], "grade3": [], "monitoring": "", "management": "" }]`

## 知识库（references）

| 参考资料 | 说明 | 使用场景 |
|----------|------|----------|
| _shared/knowledge-retrieval/SKILL.md | RAG知识库查询 | 各子Skill前置检索 |

## 工具声明（tools）

### 1、可以使用的工具、Skill等

| 工具名称 | 链接或访问方式 | 说明 | 适用场景 |
|----------|----------------|------|----------|
| sessions_spawn_parallel | 内置工具 | 并行创建多个子Agent调用子Skill | 3个子Skill并行执行 |
