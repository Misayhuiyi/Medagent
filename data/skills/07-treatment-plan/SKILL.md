---
name: 07-treatment-plan
description: 根据临床指南和专家共识选择并制定治疗方案（含肿瘤治疗+不良反应治疗+合并症治疗）。适用场景：患者概况评估完成后。不适用场景：尚未完成患者概况评估时。
version: 1.1.0
开发者: Steven Agent
changelog: |
  1.1.0 (2026-05-30): 接入RAG知识库，在每个子Skill前增加RAG检索步骤
---

# 治疗方案

肺癌医生Agent应用层第7个Skill。基于患者概况和RAG检索获取的循证知识，制定全面的治疗方案。

## 执行流程

### 1、输入
（1）06-患者概况的输出（完整概况报告）
（2）RAG知识库路径：`skills/folder-rag/database/chroma_db`（含临床指南、专家共识等）
（3）患者就诊时间（用于选择当时最新的指南版本）

### 2、步骤说明

#### 步骤0（前置步骤）：RAG检索临床指南知识
创建子Agent（`sessions_spawn`，`context="isolated"`）调用子Skill `../_shared/knowledge-retrieval/SKILL.md`：
- 根据患者肺癌类型（NSCLC/SCLC）和分子分型构建查询
- 查询内容示例：`"CSCO {年份} {NSCLC/SCLC} 治疗指南 {分期} {分子分型}"` 或 `"NCCN {年份} {NSCLC/SCLC} guidelines {stage}"`
- 年份取就诊时间前的最新版本年份
- top_k = 5，模式 = retrieve
- 输出：检索到的指南片段列表

#### 步骤1：子Agent调用「指南匹配」子Skill
创建子Agent（`sessions_spawn`，`context="isolated"`）调用 skills/guideline-matching/SKILL.md：
- 输入：步骤0的RAG检索结果 + 患者概况
- 根据RAG检索到的指南内容匹配对应治疗方案
- 以就诊时间为据选择当时最新的指南版本
- 列出可选治疗方案（含循证等级和引用来源）

#### 步骤2：子Agent调用「专家共识补充」子Skill
创建子Agent（`sessions_spawn`，`context="isolated"`）调用 skills/expert-consensus-supplement/SKILL.md：

**步骤2前置：RAG检索专家共识知识**
在调用子Skill前，先调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容示例：`"中国肺癌专家共识 {特殊临床情况}"` 或 `"{具体问题} 专家共识 治疗"`
- 根据患者概况中的特殊情况（如年龄>75、合并症多、PS评分2分等特殊情况）构建查询
- top_k = 5，模式 = retrieve
- 将检索结果作为子Skill的额外输入

子Skill执行：
- 查找患者概况中的特殊情况（指南证据不足的点）
- 使用RAG检索到的专家共识作为补充
- 比较患者概况与指南描述和专家共识描述的匹配度

#### 步骤3：子Agent调用「方案评估」子Skill
创建子Agent（`sessions_spawn`，`context="isolated"`）调用 skills/plan-evaluation/SKILL.md：
- 对每个可选方案进行疗效预测评分
- 系列不良反应预测评分
- 预后评分（进展/复发/死亡概率）
- 综合评估：方案匹配度+基因检测+ECOG评分+预测评分
- 所有评分需要引用RAG检索到的循证依据

#### 步骤4：子Agent调用「方案修改判断」子Skill
创建子Agent（`sessions_spawn`，`context="isolated"`）调用 skills/plan-modification-judgment/SKILL.md：
- 判断是否需要修改当前方案
- 按顺序判断：不良反应→疗效→可选方案
- 修改原则5种情况（严重不良反应、严重不良反应缓解后、疗效好、耐药、多药耐药）
- 输出修改后的治疗方案表格

#### 步骤5：子Agent调用「临床试验筛选」子Skill
创建子Agent（`sessions_spawn`，`context="isolated"`）调用 skills/clinical-trial-screening/SKILL.md：
- 匹配患者概况与临床试验纳排标准
- 优先本院临床试验
- 符合条件的在治疗方案中推荐

#### 步骤6：输出完整治疗方案
- 针对肿瘤的治疗方案（含药品、剂量、周期等，附RAG引用来源）
- 针对不良反应的治疗方案（若有，附RAG引用来源）
- 针对合并症的治疗方案（若有，附RAG引用来源）

### 3、条件判断

| 条件 | 处理方式 |
|------|----------|
| RAG检索无结果 | 使用模型自身知识，标注「无知识库引用依据」 |
| 指南匹配到多条 | 按循证等级排序输出，标注等级差异 |
| 严重不良反应 | 药物假期+处理不良反应，建议不良反应治疗后再次评估 |
| 严重不良反应缓解后 | 再挑战（疗效好，预防不良反应）或直接换方案（疗效不好） |
| 疗效好无严重不良反应 | 维持方案（轻度不良反应按指南观察/加强随访/干预） |
| 耐药但还有可选方案 | 维持观察评估后换方案或直接换方案 |
| 多药耐药且无指南方案 | 优先本适应症未用过药，次选其他适应症已上市药物（有研究支持） |

### 4、错误处理

| 错误类型 | 处理方案 |
|----------|----------|
| RAG脚本执行失败 | 降级为模型自身知识，标注「RAG查询失败」 |
| 指南匹配不到 | 使用更宽泛的查询词重试RAG检索 |
| 专家共识矛盾 | 以最新发布的为准 |
| 预测评分无法计算 | 标注为「暂无评分依据，需模型训练」 |

### 5、输出
（1）完整治疗方案（含选择依据、RAG引用来源、修改记录、临床试验提醒）

## 规则

### 1、被禁止的行为
（1）禁止在无RAG引用的情况下编造指南依据
（2）禁止忽略RAG检索到的指南冲突信息

### 2、约束条件
（1）所有治疗方案推荐必须在结果中标注RAG引用来源（文件名+内容片段）
（2）指南匹配结果必须包含循证等级（I类/II类推荐等）

## 知识库（references）

| 参考资料 | 资料类型 | 使用说明 | 适用场景 |
|----------|----------|----------|----------|
| _shared/knowledge-retrieval/SKILL.md | 共享子Skill | RAG知识库查询协议 | 步骤0、步骤2前置 |
| skills/guideline-matching/SKILL.md | 子Skill | 指南匹配 | 步骤1 |
| skills/expert-consensus-supplement/SKILL.md | 子Skill | 专家共识补充 | 步骤2 |
| skills/plan-evaluation/SKILL.md | 子Skill | 方案评估 | 步骤3 |
| skills/plan-modification-judgment/SKILL.md | 子Skill | 方案修改判断 | 步骤4 |
| skills/clinical-trial-screening/SKILL.md | 子Skill | 临床试验筛选 | 步骤5 |

## 任务案例（assets）

参见 assets/ 文件夹中的案例文件。

## 工具声明（tools）

### 1、可以使用的工具、Skill等

| 工具名称 | 链接或访问方式 | 说明 | 适用场景 |
|----------|----------------|------|----------|
| read | 内置工具 | 读取患者概况 | 读取输入 |
| sessions_spawn | 内置工具 | 创建子Agent调用子Skill | 调用子Skill执行 |
| exec | 内置工具 | 执行RAG查询脚本 | RAG知识检索 |
| _shared/knowledge-retrieval/SKILL.md | 共享子Skill | RAG知识库查询 | 知识检索 |
| skills/guideline-matching/SKILL.md | 子Skill | 指南匹配 | 步骤1 |
| skills/expert-consensus-supplement/SKILL.md | 子Skill | 专家共识补充 | 步骤2 |
| skills/plan-evaluation/SKILL.md | 子Skill | 方案评估 | 步骤3 |

### 2、不可使用的工具
（1）禁止跳过RAG检索直接使用模型自身知识做指南匹配
（2）禁止修改RAG数据库
