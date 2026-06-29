---
name: 05-patient-history-summary
description: 肺癌医生Agent应用层的第五个Skill。综合患者所有就诊资料，输出现病史、既往史、过敏史、个人史、家族史，并绘制疗效检测曲线、不良反应热力图、预后曲线等图表。适用场景：场景判断完成后，需要输出完整的患者病史总结报告供后续评估使用时。
version: 1.1.0
开发者: Steven Agent
changelog: |
  1.1.0 (2026-05-30): 接入RAG知识库，为图表绘制提供临床参考标准
---

# 患者病史总结

肺癌医生Agent应用层的第五个执行步骤。负责从既往AI问诊记录和出入院记录中收集、去重、荟萃总结患者的五史（现病史、既往史、过敏史、个人史、家族史），并绘制辅助分析图表。

## 执行流程

### 1、标准的输入

（1）04-场景判断的输出（场景类型、场景信息）
（2）患者资料MD文件（所有就诊时间的全部MD文件路径）
（3）既往AI问诊输出记录（如有）
（4）患者信息JSON（姓名、性别、年龄等基本信息）
（5）可选：RAG知识库路径 `skills/folder-rag/database/chroma_db`（图表绘制时参考临床标准）

### 2、步骤说明

#### 步骤1-5：并行汇总五史

五个子步骤（现病史、既往史、过敏史、个人史、家族史）互不依赖，通过并行子Agent同时执行：

创建子Agent（`sessions_spawn_parallel`，`context="isolated"`）同时调用以下5个子Skill：

```json
[
  "skills/present-illness/SKILL.md",
  "skills/past-history/SKILL.md",
  "skills/allergy-history/SKILL.md",
  "skills/personal-history/SKILL.md",
  "skills/family-history/SKILL.md"
]
```

各子Skill职责：
- **skills/present-illness/SKILL.md**：从所有就诊时间的病历、医生诊疗文件夹中提取现病史描述，从既往AI问诊记录中提取现病史信息，去重处理，以时间先后排序做成表格，绘制疗效检测曲线、不良反应热力图、预后曲线。可选：绘图前调用RAG查询临床标准。
- **skills/past-history/SKILL.md**：从所有就诊资料及既往AI问诊记录中提取既往史信息，去重荟萃，按系统分类（呼吸系统、心血管系统、消化系统等）。
- **skills/allergy-history/SKILL.md**：从所有就诊资料中提取过敏信息（药物过敏、食物过敏等），去重合并。
- **skills/personal-history/SKILL.md**：从所有就诊资料中提取个人史信息，重点提取吸烟史、职业暴露、环境因素。
- **skills/family-history/SKILL.md**：从所有就诊资料中提取家族疾病信息，重点关注肺癌及其他恶性肿瘤、遗传性疾病，记录血缘关系。

并行执行完成后，汇总所有5个子Skill的输出。

#### 步骤6：合成完整病史总结

- 合并步骤1-5（并行执行）的各子Skill输出
- 按标准顺序组织：现病史 → 既往史 → 过敏史 → 个人史 → 家族史
- 附加图表（疗效检测曲线、不良反应热力图、预后曲线）
- 输出完整的患者病史总结报告

### 3、条件判断

| 条件 | 处理方式 |
|------|----------|
| 无既往AI问诊记录（初诊）| 仅从病历和医生诊疗文件中提取 |
| 有既往AI问诊记录 | 优先使用AI问诊中的结构化信息，再补充病历信息 |
| 某类病史无数据 | 标记为「未提及」，不强行填充 |
| 同一信息在不同来源中有冲突 | 以病历和医生诊疗文件为准，标记冲突点 |
| 仅有一次就诊记录 | 一次性汇总，无时间对比图 |

### 4、错误处理

| 错误类型 | 处理方案 |
|----------|----------|
| MD文件读取失败 | 跳过该文件，在报告中标记「未读取」|
| 提取信息时无法识别病历结构 | 使用全文通读提取关键信息 |
| 绘图时数据不足 | 给出文字描述代替图表 |
| 去重时无法确定优先级 | 保留所有版本，标记为「需人工确认」|

### 5、规范的输出

```json
{
  "现病史": {
    "summary": "患者2026年1月因咳嗽、胸痛就诊...",
    "timeline": [
      {"time": "2026-01-15", "event": "初诊发现右下肺占位", "keyIndicators": {"tumorSize": "3.2cm"}, "source": "入院记录"},
      {"time": "2026-03-20", "event": "化疗2周期后复查", "keyIndicators": {"tumorSize": "2.1cm"}, "source": "出院记录"}
    ],
    "charts": {
      "efficacyCurve": ["病灶P1_疗效检测曲线.png"],
      "adverseHeatmap": "不良反应热力图.png",
      "prognosisCurve": "预后曲线.png"
    }
  },
  "既往史": {
    "summary": "",
    "details": [
      {"system": "呼吸系统", "disease": "慢性支气管炎", "time": "2020年", "status": "已治愈"},
      {"system": "心血管系统", "disease": "高血压", "time": "2018年", "status": "控制中"}
    ]
  },
  "过敏史": {
    "summary": "",
    "details": [
      {"allergen": "青霉素", "type": "药物过敏", "reaction": "皮疹", "severity": "轻度"}
    ]
  },
  "个人史": {
    "smoking": {"status": "已戒烟", "packYears": 30, "quitYear": 2025},
    "occupationalExposure": ["粉尘接触"],
    "environmentalFactors": []
  },
  "家族史": {
    "details": [
      {"relation": "父亲", "disease": "肺癌", "ageAtDiagnosis": 70}
    ]
  }
}
```

## 规则

### 1、被禁止的行为

（1）禁止在无依据的情况下编造病史信息
（2）禁止跨患者混淆病史信息
（3）禁止在信息冲突时直接删除冲突版本（应标记保留）

### 2、约束条件

（1）现病史必须按时间先后排序
（2）既往史必须按系统分类组织
（3）过敏史必须标注过敏源类型和反应严重程度
（4）个人史必须包含吸烟状态（从未吸烟/已戒烟/仍吸烟）
（5）家族史必须记录血缘关系等级
（6）信息去重时保留时间最晚的版本

### 3、鼓励的行为

（1）从多源交叉验证病史信息的准确性
（2）对关键信息（如初诊肿瘤大小）进行追踪标注
（3）图表生成时使用合适的数据可视化方式
（4）对术语进行规范化处理（如统一诊断名称）

## 知识库（references）

| 参考资料 | 资料类型 | 使用说明 | 适用场景 |
|----------|----------|----------|----------|
| 现病史/SKILL.md | 子Skill | 现病史收集、去重、荟萃 | 步骤1 |
| 既往史/SKILL.md | 子Skill | 既往史收集、去重、荟萃 | 步骤2 |
| 过敏史/SKILL.md | 子Skill | 过敏信息收集 | 步骤3 |
| 个人史/SKILL.md | 子Skill | 个人史信息收集 | 步骤4 |
| 家族史/SKILL.md | 子Skill | 家族史信息收集 | 步骤5 |

## 任务案例（assets）

参见 assets/ 文件夹中的案例文件。

## 工具声明（tools）

### 1、可以使用的工具、Skill等

| 工具名称 | 链接或访问方式 | 说明 | 适用场景 |
|----------|----------------|------|----------|
| read | 内置工具 | 读取MD文件、AI问诊记录 | 数据提取 |
| sessions_spawn_parallel | 内置工具 | 并行创建多个子Agent调用子Skill | 五史并行解析 |
| write | 内置工具 | 输出汇总报告 | 输出结果 |
| exec | 内置工具 | 绘图（调用Python脚本等方式）| 图表生成 |
| skills/present-illness/SKILL.md | 子Skill | 现病史汇总 | 步骤1 |
| skills/past-history/SKILL.md | 子Skill | 既往史汇总 | 步骤2 |
| skills/allergy-history/SKILL.md | 子Skill | 过敏史汇总 | 步骤3 |
| skills/personal-history/SKILL.md | 子Skill | 个人史汇总 | 步骤4 |
| skills/family-history/SKILL.md | 子Skill | 家族史汇总 | 步骤5 |

### 2、不可使用的工具

（1）禁止在无来源依据的情况下虚构病史信息
