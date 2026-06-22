---
name: 01-optimization-experience
description: 强化学习层Skill。总结医生修改的多个案例，寻找规律并总结优化经验，形成优化经验.md文件。适用场景：每日定期执行或医生完成多例问诊修改后。不适用场景：无医生修改案例数据时。
version: 1.0.0
开发者: Steven Agent
---

# 优化经验

强化学习层的第一个Skill。通过分析医生修改AI问诊结果的多个案例，提取修改规律和优化经验。

## 执行流程

### 1、输入
（1）医生修改过的AI问诊案例集合（含原始AI输出和医生编辑后的版本）
（2）历史优化经验.md文件（如有）

### 2、步骤说明

#### 步骤1：子Agent调用「案例分析」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/case-analysis/SKILL.md：
- 逐个分析医生修改的案例
- 对比AI输出和医生编辑版本的差异
- 提取修改模式（诊断调整、方案偏好、表述风格等）

#### 步骤2：子Agent调用「经验提取」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/experience-extraction/SKILL.md：
- 汇总所有案例中的修改模式
- 归纳共性规律和个性化偏好
- 更新优化经验.md文件
- 后续每次AI问诊启动时自动加载该经验文件

### 3、输出
（1）优化经验.md（更新后的经验文件）
（2）案例分析报告
