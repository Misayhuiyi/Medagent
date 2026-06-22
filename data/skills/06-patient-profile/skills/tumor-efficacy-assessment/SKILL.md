---
name: tumor-efficacy-assessment
description: 按iRECIST标准进行肿瘤疗效评估。适用场景：已接受治疗的患者需要疗效评估时。
version: 1.1.0
开发者: Steven Agent
changelog: |
  1.1.0 (2026-05-30): 接受父Skill传入的RAG检索结果（iRECIST标准）作为评估依据
---

# 肿瘤疗效评估

按RAG检索到的iRECIST标准评估肿瘤疗效，初诊未治疗者跳过。

## 执行流程
1. 输入：
   （1）影像报告（既往+本次）+病灶编号记录
   （2）父Skill传入的RAG检索结果（iRECIST标准片段）
2. 本次与基线比较：时间、医院、手段、大小、变化百分比
3. 本次与上一次比较
4. 最佳疗效评估（所有就诊与基线比较）
5. 按RAG检索到的iRECIST标准判定疗效（CR/PR/SD/PD）
6. 输出：疗效评估报告+病灶变化趋势表（含RAG引用标准来源）
