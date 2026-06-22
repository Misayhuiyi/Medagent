---
name: finetuning-execution
description: 执行LLM参数微调。适用场景：训练数据准备完成后。
version: 1.0.0
开发者: Steven Agent
---

# 微调执行

执行LLM参数微调并部署。

## 执行流程
1. 输入：训练数据集+医生LLM基础模型
2. 执行LoRA/全参数微调
3. 在验证集上评估效果
4. 部署微调后的模型
5. 输出：微调后模型+训练评估报告
