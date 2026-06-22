---
name: 03-clinical-experience
description: 强化学习层Skill。总结所有案例，寻找规律并总结问诊经验，形成问诊经验.md文件。适用场景：每日定期执行或积累足够问诊数据后。不适用场景：尚无问诊案例数据时。
version: 1.0.0
开发者: Steven Agent
---

# 临床经验

总结所有AI问诊案例，提取临床问诊经验。

## 执行流程

### 1、输入
（1）所有AI问诊案例集合（含AI输出和医生最终编辑版本）
（2）历史问诊经验.md文件（如有）

### 2、步骤说明

#### 步骤1：子Agent调用「问诊分析」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/consultation-analysis/SKILL.md：
- 分析所有问诊案例的流程和结果
- 识别各环节的常见问题和优化空间

#### 步骤2：子Agent调用「经验提炼」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/experience-refinement/SKILL.md：
- 提炼共性问诊经验
- 汇总为问诊经验.md文件
- 后续每次AI问诊启动时自动加载

### 3、输出
（1）问诊经验.md（更新后的经验文件）
（2）问诊分析报告
