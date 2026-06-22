---
name: 09-other-suggestions
description: 根据患者概况和选定治疗方案，输出健康教育、康复建议、护理措施。适用场景：治疗方案确定后需要输出非药物治疗建议时。不适用场景：治疗方案尚未确定时。
version: 1.1.0
开发者: Steven Agent
changelog: |
  1.1.0 (2026-05-30): 接入RAG知识库，为健教/康复/护理建议提供循证依据
---

# 其他建议

肺癌医生Agent应用层第9个Skill。基于RAG检索到的循证知识，提供健康教育、康复建议和护理措施。

## 执行流程

### 1、输入
（1）06-患者概况的输出
（2）07-治疗方案的输出
（3）08-疗效预测报告
（4）RAG知识库路径：`skills/folder-rag/database/chroma_db`

### 2、步骤说明

#### 步骤1：子Agent调用「健康教育」子Skill

**前置步骤：RAG检索健康教育相关知识**
调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容：`"肺癌患者健康教育 {治疗方案类型} {患者特点}"`
- 如：`"肺癌化疗患者健康教育 戒烟 营养 心理支持"`
- top_k = 3，模式 = retrieve
- 将检索结果作为子Skill的循证依据输入

创建子Agent（sessions_spawn, context=isolated）调用 skills/health-education/SKILL.md：
- 根据患者概况和方案输出健康教育文本
- 内容：乐观对待、按时服药、戒烟等生活方式建议
- 每个建议标注RAG检索到的循证依据来源

#### 步骤2：子Agent调用「康复建议」子Skill

**前置步骤：RAG检索康复相关知识**
调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容：`"肺癌患者康复治疗 {当前治疗阶段} {症状}"`
- 如：`"肺癌术后康复 肺功能锻炼 中药辅助"`
- top_k = 3，模式 = retrieve
- 将检索结果作为子Skill的循证依据输入

创建子Agent（sessions_spawn, context=isolated）调用 skills/rehabilitation-suggestions/SKILL.md：
- 输出康复建议（如中药保健等辅助措施，必须具有研究支持）
- 每个建议标注RAG引用的研究证据来源

#### 步骤3：子Agent调用「护理措施」子Skill

**前置步骤：RAG检索护理相关知识**
调用 `../_shared/knowledge-retrieval/SKILL.md`：
- 查询内容：`"肺癌 {治疗方案类型} 护理措施 不良反应观察"`
- 如：`"肺癌免疫治疗护理 不良反应观察 日常护理"`
- top_k = 3，模式 = retrieve
- 将检索结果作为子Skill的循证依据输入

创建子Agent（sessions_spawn, context=isolated）调用 skills/nursing-measures/SKILL.md：
- 输出护理建议（日常护理、治疗相关护理、不良反应观察）
- 每个建议标注RAG引用来源

### 3、输出
（1）其他建议报告（健康教育+康复建议+护理措施，各建议附RAG引用来源）

## 规则

### 1、禁止行为
（1）禁止提供无RAG循证依据的康复/护理建议
（2）禁止夸大或编造研究证据

### 2、约束条件
（1）每个建议必须标注RAG引用的来源文件名称
（2）康复建议中的辅助措施必须有研究支持

## 知识库（references）

| 参考资料 | 资料类型 | 使用说明 | 适用场景 |
|----------|----------|----------|----------|
| _shared/knowledge-retrieval/SKILL.md | 共享子Skill | RAG知识库查询 | 各步骤前置检索 |
| skills/health-education/SKILL.md | 子Skill | 健康教育 | 步骤1 |
| skills/rehabilitation-suggestions/SKILL.md | 子Skill | 康复建议 | 步骤2 |
| skills/nursing-measures/SKILL.md | 子Skill | 护理措施 | 步骤3 |

## 工具声明（tools）
| 工具名称 | 说明 | 适用场景 |
|----------|------|----------|
| sessions_spawn | 创建子Agent | 调用子Skill |
| exec | 执行RAG查询脚本 | RAG知识检索 |
| _shared/knowledge-retrieval/SKILL.md | RAG知识库查询 | 各步骤前置检索 |
