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

#### 步骤1：子Agent调用「疗效预测评分」子Skill

前置步骤：RAG检索方案疗效数据
- 调用 `../_shared/knowledge-retrieval/SKILL.md`
- 查询内容：`"{选定治疗药物/方案} 疗效数据 肺癌 {肿瘤类型}"`
- 查询示例：`"帕博利珠单抗 NSCLC 一线治疗 疗效数据 ORR PFS OS"`
- top_k = 5，模式 = retrieve

创建子Agent（sessions_spawn, context=isolated）调用 skills/efficacy-prediction-scoring/SKILL.md：
- 根据患者概况+RAG检索到的疗效数据对选定方案进行疗效预测评分
- 绘图：横坐标=生存时间，纵坐标=不同病灶肿瘤大小的变化曲线
- 图表中标注RAG检索到的参考数据

#### 步骤2：子Agent调用「不良反应预测评分」子Skill

前置步骤：RAG检索不良反应数据
- 调用 `../_shared/knowledge-retrieval/SKILL.md`
- 查询内容：`"{选定治疗药物/方案} 不良反应 {常见不良反应类型}"`
- 查询示例：`"帕博利珠单抗 不良反应 免疫相关不良反应 发生率"`
- top_k = 5，模式 = retrieve

创建子Agent（sessions_spawn, context=isolated）调用 skills/adverse-event-prediction/SKILL.md：
- 预测系列不良反应及其概率
- 绘图：1种不良反应1张图，横坐标=生存时间，纵坐标=不同等级不良反应发生率
- 标注RAG检索到的参考发生率

#### 步骤3：子Agent调用「预后预测评分」子Skill

前置步骤：RAG检索预后数据
- 调用 `../_shared/knowledge-retrieval/SKILL.md`
- 查询内容：`"{选定治疗药物/方案} 预后数据 肺癌 {分期} 生存率"`
- top_k = 5，模式 = retrieve

创建子Agent（sessions_spawn, context=isolated）调用 skills/prognosis-prediction/SKILL.md：
- 预测进展/复发/死亡概率
- 绘图：单张图，横坐标=生存时间，纵坐标=三条概率曲线
- 图表中标注RAG检索到的参考数据

### 3、输出
（1）疗效预测报告（含评分+图表+RAG引用）
（2）不良反应预测报告（含评分+图表+RAG引用）
（3）预后预测报告（含评分+图表+RAG引用）

## 知识库（references）

| 参考资料 | 说明 | 使用场景 |
|----------|------|----------|
| _shared/knowledge-retrieval/SKILL.md | RAG知识库查询 | 各步骤前置检索 |
| skills/efficacy-prediction-scoring/SKILL.md | 疗效预测评分 | 步骤1 |
| skills/adverse-event-prediction/SKILL.md | 不良反应预测 | 步骤2 |
| skills/prognosis-prediction/SKILL.md | 预后预测评分 | 步骤3 |
