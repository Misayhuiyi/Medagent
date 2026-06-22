---
name: scenario-matching
description: 根据患者资料特征判断当前就诊所属的6种就诊场景之一。适用场景：在场景判断流程中，需要根据资料特征自动匹配场景类型时。
version: 1.0.0
开发者: Steven Agent
---

# 场景匹配

肺癌医生Agent场景判断流程的核心子Skill。负责分析患者资料特征，通过规则匹配确定所属的6种就诊场景类型。

## 执行流程

### 1、标准的输入

（1）患者资料特征标识（已由主Skill提取）：
- `hasSymptoms`: 是否有症状描述
- `symptomDetail`: 症状具体描述
- `hasImaging`: 是否有影像检查报告
- `hasPathology`: 是否有病理检查报告
- `hasLabTest`: 是否有检验检查报告
- `hasHealthCheck`: 是否有体检信息
- `hasPriorTreatment`: 是否有既往治疗记录
- `hasTransferInfo`: 是否有外院转诊信息
- `hasImagingFinding`: 是否有明确的影像学发现
- `isFollowUpCheck`: 是否为治疗后复查

（2）可选：详细的MD文件内容摘要

### 2、步骤说明

#### 步骤1：构建特征向量

- 将输入的特征标识转换为布尔特征向量
- 特征向量维度：症状、影像、病理、检验、体检、既往治疗、转诊、影像发现、复查标记

#### 步骤2：按优先级规则匹配场景

**层级1：转诊检查（优先级最高）**
- 条件：`hasTransferInfo === true`
- 判断：如果有明确的转诊资料，直接判定为场景4
- 子条件：区分转诊后是否已做新检查，但不影响场景4的判断

**层级2：有既往治疗记录**
- 条件：`hasPriorTreatment === true`
- 子判断2a：`isFollowUpCheck === true` → 场景6（治疗后检查复诊）
- 子判断2b：`isFollowUpCheck === false` → 场景5（治疗后未检查）
- 注意：检查既往治疗记录是否存在（手术史、化疗史、放疗史、靶向/免疫治疗史）

**层级3：初诊（无既往治疗）**
- 条件：`hasPriorTreatment === false` AND `hasTransferInfo === false`
- 子判断3a：`hasSymptoms === true` AND `(hasImaging === true OR hasPathology === true OR hasLabTest === true)` → 场景2（检查后初诊）
- 子判断3b：`hasSymptoms === false OR 症状不明显` AND `hasImagingFinding === true` AND `hasHealthCheck === true` → 场景3（早筛怀疑初诊）
- 子判断3c：`hasSymptoms === true` AND `hasImaging === false` AND `hasPathology === false` AND `hasLabTest === false` → 场景1（未检查初诊）

**层级4：无法匹配**
- 其他情况 → 标记为「场景待定」，由人工判断

#### 步骤3：验证匹配结果

- 确认匹配结果与所有输入特征不矛盾
- 如有场景重叠，按优先级决定
- 生成判断依据文本

#### 步骤4：输出匹配结果

- 输出场景类型和完整判断依据

### 3、条件判断

| 条件 | 匹配场景 |
|------|----------|
| 有转诊信息 | 场景4 |
| 有既往治疗+有新检查 | 场景6 |
| 有既往治疗+无新检查 | 场景5 |
| 无既往治疗+有症状+有检查 | 场景2 |
| 无既往治疗+症状不明显+影像提示+有体检 | 场景3 |
| 无既往治疗+有症状+无检查 | 场景1 |
| 以上都不符合 | 场景待定（需人工确认）|

### 4、错误处理

| 错误类型 | 处理方案 |
|----------|----------|
| 特征标识不完整（部分字段缺失）| 缺失字段默认为false，标记为「特征不完整」|
| 所有特征均为false | 判定为场景待定 |
| 转诊但有更多特征指向其他场景 | 以转诊为优先，标记双特征 |
| 既往治疗+转诊同时存在 | 以转诊优先，标记「有既往治疗史的转诊」|

### 5、规范的输出

```json
{
  "sceneType": "场景2",
  "sceneName": "检查后初诊",
  "sceneInfo": {
    "hasSymptoms": true,
    "symptomList": ["咳嗽", "胸痛"],
    "hasImaging": true,
    "hasPathology": false,
    "hasLabTest": true,
    "hasHealthCheck": false,
    "hasPriorTreatment": false,
    "hasTransferInfo": false,
    "hasImagingFinding": true,
    "isFollowUpCheck": false
  },
  "judgmentBasis": "匹配链条：层级3→子判断3a：有症状+有影像和检验检查。符合场景2（检查后初诊）特征。",
  "boundaryFlag": false,
  "alternateScenes": []
}
```

## 规则

### 1、被禁止的行为

（1）禁止在无转诊证据的情况下判定为场景4
（2）禁止在无治疗记录的情况下判定为场景5或6
（3）禁止主观臆断特征值（所有特征必须有资料依据）

### 2、约束条件

（1）场景匹配必须严格按优先级规则执行
（2）必须记录完整的匹配链条作为判断依据
（3）边界场景必须标记并提示人工确认

### 3、鼓励的行为

（1）对不明确的特征进行二次确认（如通过MD内容搜索关键词）
（2）对于场景重叠的情况，提供多个候选场景供选择
（3）建立置信度评分机制

## 工具声明（tools）

### 1、可以使用的工具、Skill等

| 工具名称 | 链接或访问方式 | 说明 | 适用场景 |
|----------|----------------|------|----------|
| read | 内置工具 | 读取MD文件内容进行特征二次确认 | 验证特征 |

### 2、不可使用的工具

（1）禁止在无依据的情况下修改特征标识
