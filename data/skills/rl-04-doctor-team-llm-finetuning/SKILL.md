---
name: 04-doctor-team-llm-finetuning
description: 强化学习层Skill。定期收集多医生经验文件进行融合，训练多中心多医生经验的医生Agent。适用场景：多位医生使用AI医生Agent并积累足够经验后。不适用场景：只有单医生数据时。
version: 1.0.0
开发者: Steven Agent
---

# 医生团队LLM模型微调强化

融合多医生经验进行团队级LLM微调。

## 执行流程

### 1、输入
（1）多位医生的优化经验.md文件
（2）多位医生的问诊经验.md文件
（3）多医生的微调模型

### 2、步骤说明

#### 步骤1：子Agent调用「经验融合」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/experience-fusion/SKILL.md：
- 收集并融合多位医生的经验文件
- 识别共识经验和个性化差异
- 生成融合后的训练数据

#### 步骤2：子Agent调用「团队微调」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/team-finetuning/SKILL.md：
- 基于融合数据执行团队级LLM微调
- 训练多中心多医生经验的医生Agent
- 部署团队医生模型

### 3、输出
（1）融合后的团队医生LLM模型
（2）经验融合报告
