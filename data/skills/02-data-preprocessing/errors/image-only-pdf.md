---
错误时间: 2026-05-30 13:16
错误Skill: 02-data-preprocessing
子Skill: pdf-conversion
测试案例: 张三（刘海平）
---

# 图片型PDF无法提取文本

## 现象
34个影像报告PDF（如 `20231205003404v2.pdf`）使用pypdfium2提取文本后字符数为0，全部为扫描件/截图。

## 原因分析
医院影像报告以图片格式（截图或DICOM打印）导出为PDF，不包含可提取的文本层。

## 影响
- 后续AI问诊环节无法直接获取影像报告中的关键信息
- 目前标记为IMAGE_ONLY，下游Skill需识别并跳过或走OCR路径

## 修复建议
1. 在 `pdf-conversion/SKILL.md` 中增加OCR检测逻辑：当文本长度为0时标记 `needs_ocr: true`
2. 集成EasyOCR对图片型PDF进行识别（可复用 `folder-rag` 技能的OCR能力）
3. 在PDF转换报告中增加 `needs_ocr` 字段，供下游Skill感知

## 已处理
- 确认所有影像报告均为图片型
- 在转换报告 `conversion_report.json` 中标记
