---
name: pdf-conversion
description: 将PDF格式的患者资料文件预处理为MD格式文件。支持双模式：Pipeline模式下已预提取则只做验证；独立模式下扫描目录执行全量转换。
version: 1.2.0
开发者: Steven Agent
changelog: |
  1.2.0 (2026-06-23): 输入描述从"就诊时间文件夹路径"改为通用"患者资料目录路径"，适配Pipeline（TempData/patients/）和独立模式（本地患者库）双场景
  1.1.0 (2026-05-30): 集成OCR引擎处理图片型PDF；增加合并检验报告按日期拆分功能
---

# PDF转换

肺癌医生Agent资料预处理流程的第三步。支持两种PDF类型的处理：
1. **文本型PDF**：直接使用 pypdf2 提取文本
2. **图片型PDF**：使用 pypdfium2 + EasyOCR 进行光学字符识别

支持合并检验报告PDF按检查日期自动拆分。

## 执行流程

### 1、标准的输入

（1）患者资料目录路径（含 PDF 文件的目录，通常包含影像报告/病理报告/检验报告/病历/医生诊疗 等子文件夹）。Pipeline 模式下为 `TempData/patients/{patient_id}/`，独立模式下为 `本地患者库/{患者姓名}_{门诊号}/{就诊时间}/`。
（2）待转换的 PDF 文件列表（可选，不传则自动扫描目录下所有 PDF）

### 2、步骤说明

#### 前置步骤：合并PDF拆分（检验报告/多页合并文件）

调用 `skills/肺癌医生Agent/scripts/lab_report_splitter.py` 进行拆分：

```bash
python "skills/肺癌医生Agent/scripts/lab_report_splitter.py" \
  --mode batch \
  --input "{患者资料目录}/检验报告" \
  --output "{患者资料目录}/检验报告"
```

- 对页数 >= 3 的PDF进行日期边界检测
- 按检查日期拆分为独立PDF
- 拆分后的文件命名格式：`{原文件名}_{YYYY-MM-DD}.pdf`
- 生成 `split_report.json` 记录拆分结果

#### 步骤1：检查是否已有MD文件（如有则跳过转换）

**检查各资料类型子文件夹**：遍历患者资料目录下所有子文件夹，检查 `ocr/` 子目录或与 PDF 同级的 `.md` 文件是否已存在。

- 如果各子文件夹中已有 `.md` 文件 → 说明之前已转换过，直接跳到步骤3（验证已有 MD 文件）
- 如果都不存在 `.md` 文件 → 进入步骤2进行 PDF 转换

#### 步骤2：批量PDF→MD转换（仅当无已有MD文件时执行）

**使用 `batch_pdf_to_md` 工具**，一次性转换目录下所有PDF。

- 调用 `batch_pdf_to_md(dir_path="患者资料目录路径")`
- 工具自动扫描目录下所有 PDF，用 pymupdf 提取文本
- 返回转换结果报告（含每个文件的 status / pageCount / charCount）

**备选方案**（仅当 `batch_pdf_to_md` 工具不可用时才使用）：


对于每个PDF文件，按以下流程处理：

##### 子步骤2.1：检测PDF类型（文本型/图片型）

使用 pypdf2 提取前5页文本，如果平均每页字符数 < 50，则判定为图片型PDF。

##### 子步骤2.2A：文本型PDF转换

- 使用 pypdf2 提取文本内容和元数据
- 提取文档标题、作者、创建日期等元信息
- 结构化转换：保留标题层级、表格（转MD表格格式）、段落结构

##### 子步骤2.2B：图片型PDF（OCR识别）

调用 `skills/肺癌医生Agent/scripts/pdf_ocr_processor.py`：

```bash
python "skills/肺癌医生Agent/scripts/pdf_ocr_processor.py" \
  --mode single \
  --input "{PDF文件路径}" \
  --output "{MD文件路径}" \
  --lang ch_sim+en \
  --dpi 200
```

- 使用 pypdfium2 按200DPI渲染PDF页面为图片
- 使用 EasyOCR（ch_sim+en）识别中英文文本
- 输出结果按页面标记 `--- Page N ---` 分隔
- 转换后的MD文件命名：`{原PDF文件名}_ocr.md`

##### 子步骤2.3：保存MD文件

- 文件名格式：`{原PDF文件名（不含扩展名）}.md`（文本型）或 `{原PDF文件名}_ocr.md`（OCR型）
- 保存路径：与原始 PDF 相同的子文件夹下的 `ocr/` 子目录
- 如果同名MD文件已存在且内容相同，跳过不覆盖
- 如果同名MD文件已存在但内容不同，使用 `{原文件名}_v{版本号}.md` 格式

#### 步骤3：验证MD文件完整性（已有文件或新生成文件通用）

- 抽样阅读 2-3 个 MD 文件，确认内容正确（标题、段落、关键数据）
- 检查 MD 文件大小是否合理（不应为空或过小）
- 统计文件总数，确认覆盖了所有 PDF
- 标记异常的文件（空内容 / 乱码 / 格式损坏）

#### 步骤4：生成转换日志

- 记录每个文件的转换状态（成功/失败/跳过/OCR）
- 记录转换耗时和文件大小变化
- 输出转换结果清单（含 `conversion_report.json`）

### 3、条件判断

| 条件 | 处理方式 |
|------|----------|
| PDF文件有文本层（非扫描件）| 直接提取文本和结构 |
| PDF文件无文本层（扫描件）| 使用EasyOCR引擎识别（pypdfium2渲染+OCR） |
| PDF文件为合并检验报告（多页）| 先拆分再逐份转换 |
| PDF文件损坏或加密 | 标记为「转换失败」，记录错误信息 |
| 转换成功但MD内容为空 | 标记为「可能为图片型PDF」，尝试OCR |
| OCR识别率低（<50字符/页）| 标记为「OCR质量低，建议人工校对」 |

### 4、错误处理

| 错误类型 | 处理方案 |
|----------|----------|
| PDF解析工具不可用 | 尝试备用解析方法 |
| EasyOCR模型未下载 | 提示首次使用需联网下载模型 |
| OCR处理超时 | 降低DPI或减少并发处理 |
| 合并PDF拆分失败 | 按原始文件整体转换，标记为「未拆分」|
| 内存不足 | 分批处理大文件 |

### 5、规范的输出

```json
{
  "conversionResults": [
    {
      "sourceFile": "影像报告/CT报告.pdf",
      "targetFile": "影像报告/CT报告.md",
      "status": "success",
      "method": "text",
      "pageCount": 3,
      "charCount": 4500,
      "conversionTimeMs": 1200
    },
    {
      "sourceFile": "影像报告/getReportSnaphotPath.pdf",
      "targetFile": "影像报告/getReportSnaphotPath_ocr.md",
      "status": "success_ocr",
      "method": "ocr",
      "pageCount": 1,
      "charCount": 320,
      "conversionTimeMs": 8500
    },
    {
      "sourceFile": "检验报告/住院.pdf",
      "targetFile": "检验报告/split/住院_2024-04-18.pdf",
      "status": "split",
      "method": "split+text",
      "pageCount": 15,
      "charCount": 12000,
      "conversionTimeMs": 3000
    }
  ],
  "splitInfo": {
    "住院.pdf": {"status": "split", "parts": 5},
    "门诊.pdf": {"status": "single", "pages": 1}
  },
  "totalFiles": 3,
  "successCount": 2,
  "ocrCount": 1,
  "splitCount": 1,
  "failCount": 0,
  "mdFilePaths": [
    ".../影像报告/CT报告.md",
    ".../影像报告/getReportSnaphotPath_ocr.md",
    ".../检验报告/split/住院_2024-04-18.md"
  ]
}
```

## 规则

### 1、被禁止的行为
（1）禁止修改或删除原始PDF文件
（2）禁止在OCR过程中丢失表格或关键数值数据
（3）禁止跨资料类型混放转换后的MD文件

### 2、约束条件
（1）MD文件名必须与PDF文件名保持一致（扩展名不同，OCR文件加_ocr后缀）
（2）必须保留原始文档结构（标题层级、段落、列表、表格）
（3）OCR结果必须在MD中标记为 `[OCR识别]` 以区别于标准文本提取
（4）MD文件编码必须为UTF-8

### 3、鼓励的行为
（1）在MD文件中保留原PDF页面标记（如 `--- Page 2 ---`）
（2）对于OCR结果，保留识别置信度信息
（3）大文件（>50页）逐页转换并记录每页结果

## 工具声明（tools）

### 1、可以使用的工具、Skill等

| 工具名称 | 链接或访问方式 | 说明 | 适用场景 |
|----------|----------------|------|----------|
| batch_pdf_to_md | 内置工具 | **批量PDF→MD转换（推荐）**：一次调用转换目录下所有PDF，替代逐文件exec循环 | 批量PDF转换 |
| read | 内置工具 | 读取转换结果 | 验证转换质量 |
| write | 内置工具 | 写入转换后的MD文件 | 输出结果 |
| pdf_ocr_processor.py | `skills/肺癌医生Agent/scripts/pdf_ocr_processor.py` | OCR处理图片型PDF | OCR识别 |
| lab_report_splitter.py | `skills/肺癌医生Agent/scripts/lab_report_splitter.py` | 合并PDF按日期拆分 | PDF拆分 |

### 2、不可使用的工具
（1）禁止跳过PDF转换直接传递PDF到下游
（2）禁止使用不可靠的在线PDF转换API
（3）禁止在无OCR的情况下丢弃图片型PDF
