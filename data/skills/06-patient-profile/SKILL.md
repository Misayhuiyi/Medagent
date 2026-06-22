---
name: 06-patient-profile
description: 肺癌医生Agent应用层第6个Skill。综合患者全面信息，输出完整的患者概况报告，包括主诉、体格检查、辅助检查、肿瘤负荷评估、肿瘤疗效评估、不良反应评估、合并症评估、ECOG-PS评分、补充资料、诊断总结。适用场景：场景判断和患者病史总结完成后。不适用场景：尚未完成患者病史总结时。
version: 1.1.0
开发者: Steven Agent
changelog: |
  1.1.0 (2026-05-30): 接入RAG知识库，为肿瘤负荷评估/疗效评估/不良反应评估等环节提供循证依据
---

# 患者概况

肺癌医生Agent应用层的核心评估步骤。基于患者病史总结、原始资料和RAG检索获得的循证知识，输出全面的患者概况评估，为治疗方案制定提供依据。

## 执行流程

### 1、标准的输入

（1）05-患者病史总结的输出（结构化病史报告）
（2）患者资料MD文件（原始检查报告）
（3）RAG知识库路径：`skills/folder-rag/database/chroma_db`（含临床指南、专家共识、CTCAE标准、TNM分期标准等）

### 2、步骤说明

#### 步骤1：子Agent调用子Skill「主诉分析」
在当前主流程中直接分析，或创建子Agent调用子Skill，提取：
- 肿瘤分型（病理类型、分期）
- 治疗方案+治疗时间（如有）
- 不良症状
- 合并症状

#### 步骤2：子Agent调用子Skill「体格检查提取」
创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/physical-examination/SKILL.md`：
- 从入院记录中提取体格检查信息
- 展示异常指标和关键信息：血氧(SpO2)、体温(T)、心率(P)、呼吸频率(R)、血压(BP)等
- 标记异常值

#### 步骤3：子Agent调用子Skill「辅助检查分析」
创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/auxiliary-examination/SKILL.md`：
- 从影像报告、病理报告、检验报告中提取异常和关键信息
- 包括：肿瘤分型、基线最大肿瘤大小、本次最大肿瘤大小、基因检测与分子分型
- 标注检查医院和检查时间

#### 步骤4：子Agent调用子Skill「肿瘤负荷评估」
**前置步骤：RAG检索TNM分期标准**
在调用子Skill前，调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容：`"TNM第九版肺癌TNM分期标准"` 或 `"TNM 9th edition lung cancer staging"`
- top_k = 3，模式 = retrieve
- 将检索结果作为子Skill的循证依据输入

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/tumor-burden-assessment/SKILL.md`：
- T分期：根据Top3大小病灶，依据RAG检索到的TNM第九版标准
- N分期：根据淋巴结转移情况（含穿刺活检确认）
- M分期：根据远端脏器转移情况
- TNM分期总结及对应临床分期
- 病灶编号统一管理（P1,P2...；LN1,LN2...；M1,M2...）

#### 步骤5：子Agent调用子Skill「肿瘤疗效评估」
**前置步骤：RAG检索iRECIST疗效评估标准**
在调用子Skill前，调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容：`"iRECIST标准 肿瘤疗效评估 完全缓解 部分缓解 疾病稳定 疾病进展"`
- top_k = 3，模式 = retrieve
- 将检索结果作为子Skill的循证依据输入

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/tumor-efficacy-assessment/SKILL.md`：
- 本次与基线比较：展示时间、医院、检测手段、具体大小，计算变化
- 本次与上一次比较
- 最佳疗效评估：所有就诊与基线比较
- 按iRECIST标准评估（使用RAG检索到的标准）
- 初诊未治疗者跳过本步骤，标记为"初诊未治疗，无需疗效评估"

#### 步骤6：子Agent调用子Skill「不良反应评估」
**前置步骤：RAG检索CTCAE不良反应标准**
在调用子Skill前，调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容：`` `CTCAE 6.0 {当前治疗药物类型} 不良反应分级标准` `` 或 `"免疫相关不良反应 CTCAE 分级"`
- 根据患者当前用药类型（如化疗、免疫、靶向等）针对性查询
- top_k = 5，模式 = retrieve
- 将检索结果作为子Skill的循证依据输入

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/adverse-event-assessment/SKILL.md`：
- 从症状、体征、辅助检查中提取不良反应相关信息
- 遍历评估各种不良反应等级（依据RAG检索到的CTCAE标准、指南、专家共识）
- 初诊未治疗者跳过，仅评估非治疗相关的合并症状
- 标注依据来源（RAG引用的文件名称）

#### 步骤7：子Agent调用子Skill「合并症评估」
**前置步骤：RAG检索合并症相关知识**
在调用子Skill前，调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容：`"肺癌常见合并症 {已识别合并症名称} 处理"` 或根据已识别的合并症调整查询
- top_k = 3，模式 = retrieve
- 将检索结果作为子Skill的循证依据输入

创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/comorbidity-assessment/SKILL.md`：
- 排除本疾病（肺癌）和已识别的不良反应，避免重复
- 根据RAG检索到的知识综合评估

#### 步骤8：子Agent调用子Skill「ECOG评分」
创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/ecog-score/SKILL.md`：
- 综合入院记录、体格检查、患者对话等评估ECOG-PS评分
- 评分范围0-5分

#### 步骤9：补充资料整理
- 既往基因检测结果（表格输出：时间-检测项目-结果）
- 历史治疗方案（表格输出：时间-药物方案-实际治疗效果-不良反应）

#### 步骤10：子Agent调用子Skill「诊断总结」
创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `skills/diagnosis-summary/SKILL.md`：
- 肿瘤诊断（含RAG引用的分期标准）
- 不良反应诊断（含RAG引用的CTCAE标准）
- 合并症诊断
- ECOG评分
- 补充资料

### 3、条件判断

| 条件 | 处理方式 |
|------|----------|
| 初诊未治疗 | 跳过步骤5和步骤6的RAG前置检索 |
| 已接受治疗 | 完整执行所有RAG检索和评估步骤 |
| 病灶追踪 | 保持病灶编号统一，贯穿全生命周期 |
| RAG检索无结果 | 使用模型自身知识，标注「无知识库依据」|

### 4、错误处理

| 错误类型 | 处理方案 |
|----------|----------|
| 检查资料缺失 | 标记为"缺失"，注明需要补充的资料类型 |
| 分期判断模糊 | 取保守分期，注明RAG检索到的判断依据和可能的替代分期 |
| 历史病灶编号不一致 | 根据部位和时间追溯，更新编号映射 |
| RAG脚本执行失败 | 降级为模型自身知识，标注「RAG查询失败」|

### 5、规范的输出

（1）患者概况报告（包含上述所有步骤的输出，每个引用标注RAG来源文件名）
（2）每个评估步骤的AI评分和依据引用

## 规则

### 1、被禁止的行为

（1）禁止在不同就诊间改变同一病灶的编号
（2）禁止合并不同检查时间的肿瘤测量数据
（3）禁止跳过知识库引用——每个需要临床标准的步骤必须RAG检索
（4）禁止在无RAG引用的情况下编造分期/疗效/不良反应等级

### 2、约束条件

（1）分期必须引用RAG检索到的TNM第九版标准
（2）疗效评估必须使用RAG检索到的iRECIST标准
（3）不良反应评估必须引用RAG检索到的CTCAE版本和来源指南
（4）RAG引用格式："文件名"+"内容片段"

### 3、鼓励的行为

（1）在每项评估结果后标注RAG引用的知识资料
（2）对不确定的判断标注置信度
（3）优先使用最新指南和专家共识

## 知识库（references）

| 参考资料 | 资料类型 | 使用说明 | 适用场景 |
|----------|----------|----------|----------|
| _shared/knowledge-retrieval/SKILL.md | 共享子Skill | RAG知识库查询协议 | 步骤4/5/6/7前置检索 |
| skills/tumor-burden-assessment/SKILL.md | 子Skill | 肿瘤负荷评估 | 步骤4 |
| skills/tumor-efficacy-assessment/SKILL.md | 子Skill | 肿瘤疗效评估 | 步骤5 |
| skills/adverse-event-assessment/SKILL.md | 子Skill | 不良反应评估 | 步骤6 |
| skills/comorbidity-assessment/SKILL.md | 子Skill | 合并症评估 | 步骤7 |
| skills/physical-examination/SKILL.md | 子Skill | 体格检查提取 | 步骤2 |
| skills/auxiliary-examination/SKILL.md | 子Skill | 辅助检查分析 | 步骤3 |
| skills/ecog-score/SKILL.md | 子Skill | ECOG评分 | 步骤8 |
| skills/diagnosis-summary/SKILL.md | 子Skill | 诊断总结 | 步骤10 |

## 任务案例（assets）

参见 assets/ 文件夹中的案例文件。

## 工具声明（tools）

### 1、可以使用的工具、Skill等

| 工具名称 | 链接或访问方式 | 说明 | 适用场景 |
|----------|----------------|------|----------|
| read | 内置工具 | 读取MD文件 | 数据提取 |
| sessions_spawn | 内置工具 | 创建子Agent调用子Skill | 调用子Skill |
| exec | 内置工具 | 执行RAG查询脚本 | RAG知识检索 |
| write | 内置工具 | 输出汇总报告 | 输出结果 |
| _shared/knowledge-retrieval/SKILL.md | 共享子Skill | RAG知识库查询 | 步骤4/5/6/7前置检索 |

### 2、不可使用的工具

（1）禁止在无来源依据的情况下虚构分期/疗效/不良反应等级
（2）禁止跳过RAG检索直接评估
