---
name: 02-doctor-llm-finetuning
description: 强化学习层Skill。基于优化经验和医生案例进行医生个人LLM参数微调强化。适用场景：有足够的医生修改案例数据后定期执行。不适用场景：数据不足或模型微调环境未就绪时。
version: 1.0.0
开发者: Steven Agent
---

# 医生LLM模型微调强化

基于医生个人案例进行LLM参数微调。

## 执行流程

### 1、输入
（1）优化经验.md文件
（2）医生修改案例数据集
（3）医生个人LLM基础模型

### 2、步骤说明

#### 步骤1：子Agent调用「数据准备」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/data-preparation/SKILL.md：
- 整理医生修改案例为微调训练数据
- 构建输入输出对（原始AI输出→医生编辑后版本）

#### 步骤2：子Agent调用「微调执行」子Skill
创建子Agent（sessions_spawn, context=isolated）调用 skills/finetuning-execution/SKILL.md：
- 执行LLM参数微调
- 验证微调效果
- 部署更新后的医生个人模型

### 3、输出
（1）微调后的医生LLM模型
（2）微调训练报告
