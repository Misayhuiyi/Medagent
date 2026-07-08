# MedAgent 项目记忆

> 最后更新：2026-07-08（V3.6 — normalizer 噪声过滤增强 + pdf_renderer 安全加固 + 知识库/Hotfix/迭代完结）

## 项目概述

MedAgent 三阶段重构升级项目。已完成阶段一（空白 Agent 框架提取）和阶段二（肺癌医生流程集成 + 前端渲染修复 + 知识库升级 + PDF 导出对齐）。当前 V3.6，阶段三（RAG→SAG 重构）待启动。

## 当前阶段

**阶段二（肺癌医生流程集成）**：✅ 功能集成+稳定性修复+性能优化全部完成。

当前状态：

- 前端 5 报告页签稳定展示（FigmaReportCard + ECharts + ClinicalText 语义高亮）
- PDF 导出对齐 old_MedAgent：Playwright Chromium > Edge无头 > wkhtmltopdf > fpdf2 四级回退
- 知识库升级到 279 篇指南/44307 块（Ollama bge-m3 + CrossEncoder 精排）
- 支持跨时间段连续报告生成
- Understand Anything 插件安装并完成全量 7 阶段分析（468 节点/597 边/12 层/8 步导览）

| 版本 | 日期 | 内容 | 状态 |
|------|------|------|:----:|
| V2.0-V2.3 | 06-23~06-25 | 全量代码审计、OCR跳过、递归上限修复、就诊选择、子Agent并行化 | ✅ |
| V2.4-V2.6 | 06-29 | 快速模式(跳过01-04)、双温度配置、V4模板PDF导出 | ✅ |
| **V2.9** | **07-06** | **PDF内容截断修复(40.5%→76.1%) + 知识库升级(279篇/44K块)** | ✅ |
| **V3.0-V3.3** | **07-06** | **跨时间连续报告 + 展示修复 + KB链路 + JSON噪声修复** | ✅ |
| **V3.4** | **07-06** | **Playwright PDF对齐 + ClinicalText自动高亮** | ✅ |
| **V3.5** | **07-07** | **上传患者资料执行方案 + normalizer结构化检测增强** | ✅ |
| **V3.6** | **07-08** | **normalizer噪声过滤 + pdf_renderer安全加固 + ClinicalText词库扩展** | ✅ |

## 项目结构

```
ai医生完整/
├── MedAgentNEW/           # 当前工作项目 — V3.6
├── old_MedAgent/           # 旧版 MedAgent（参考源）
├── knowledge-base/         # 279 篇指南源文件
├── 更新/                   # 已接入
├── 任务需求与执行规划.md   # 三阶段规划文档
└── project_memory.md       # 本文件
```

## MedAgentNEW 关键目录

```
MedAgentNEW/
├── Code/
│   ├── main.py                     # 唯一主入口（web/cli/blank 三模式）
│   └── DataCode/                   # 后端核心模块
│       ├── reporting/              # V4 HTML/PDF 模板引擎（normalizer/template_v4/pdf_renderer_v4）
│       ├── report_context.py       # 跨时间段报告上下文
│       ├── skill_executor.py       # 10步流水线引擎 + LLM容灾
│       └── web_routes/             # 5个API路由模块
├── Data/
│   ├── skills/                     # 15主Skill + 43子Skill
│   ├── knowledge_base/             # ChromaDB(Ollama bge-m3) + CrossEncoder
│   │   ├── tool.py                 # ChromaDB 语义搜索 + 双语扩展 + 意图解析
│   │   ├── kb_manager.py           # 新知识库引擎
│   │   └── chroma_db/              # 279篇指南/44307块（679MB）
│   └── platform.yaml               # 双温度配置
├── frontend/                       # React 19 + TypeScript + Ant Design 6
│   └── src/components/ReportPanel/
│       ├── index.tsx               # 三级回退渲染 + findBalancedJson + extractStructuredJsonFromText
│       ├── ClinicalText.tsx        # 语义高亮（自动/手动模式）
│       ├── chartData.ts            # 图表数据归一化工具
│       └── textFormat.ts           # 文本递归格式化
├── .understand-anything/           # Understand Anything 知识图谱产物
│   └── knowledge-graph.json        # 468节点/597边/12层/8步导览
├── TempData/patients/              # 4名患者（张三21/李四9/王五17/刘海平100 PDF）
└── Result/                         # 报告输出 + Pipeline日志
```

## 核心架构

- **后端**：FastAPI + LangGraph ReAct（deep_agent.py 工厂）
- **前端**：React 19 + TypeScript + Ant Design 6 + Zustand 5 + ECharts 6
- **知识检索**：ChromaDB + Ollama bge-m3（默认快速向量召回，可选 CrossEncoder 精排）
- **PDF 导出**：Playwright Chromium（主）→ Edge 无头打印（备）→ wkhtmltopdf → fpdf2（兜底）
- **温度隔离**：报告 temperature=0 / 对话 chat_temperature=0.1（platform.yaml 唯一入口）
- **Understand Anything**：已安装插件，已生成 Complete 知识图谱
- **仪表盘**：http://127.0.0.1:5173/?token=medagent2026（双击桌面 run_dashboard.ps1 启动）

## 运行状态

| 组件 | 状态 | 地址 |
|------|------|------|
| 后端 FastAPI | ✅ 运行中 | http://localhost:8000 |
| 前端 Vite | ✅ 运行中 | http://localhost:3000 |
| Ollama bge-m3 | ✅ 已加载 | http://localhost:11434 |
| 空白验证 | 9/9 PASS | `python Code/main.py blank` |
| 知识库 | 279 篇指南/44307 块 | Data/knowledge_base/ |
| 仪表盘 | 可启动 | desktop/run_dashboard.ps1 |

## 关键技术决策（V2.9-V3.6 新增）

1. **PDF 内容截断修复**：normalizer `_polish_content` max_chars 1300→12000，未匹配章节自动追加
2. **知识库升级**：旧 KB（bge-small-zh-v1.5, 121PDF/30K块）→ 新 KB（Ollama bge-m3, 279篇/44K块，CrossEncoder 精排）
3. **环境变量延迟加载**：kb_manager COLLECTION_NAME 改为 `_get_collection_name()` 函数实时读环境变量
4. **前端 `enhanceFromWrapper`**：从 `{step, result, _content}` 包装对象提取嵌套 JSON，结构化渲染触发率提高
5. **前端 `extractStructuredJsonFromText`**：从 Markdown 中扫描 ````json```` / `完整结构化输出` 等标记提取 JSON
6. **Playwright PDF**：新增 Playwright Chromium 为 PDF 首选方案（与 old_MedAgent 一致），Playwright > Edge > wkhtmltopdf > fpdf2 四级回退
7. **ClinicalText autoHighlights**：无高亮数据时自动识别医学术语着色（红=不良反应、蓝=肿瘤、绿=治疗）
8. **Understand Anything**：完成全量 7 阶段分析（191 文件扫描、468 节点/597 边、12 架构层、8 步导览）
9. **normalizer 噪声过滤增强**：ABBREVIATION_EXPANSIONS 医学缩写展开、PROCESS_LINE_PATTERNS 正则过滤、TREATMENT_SECTION_TITLES 结构化检测
10. **pdf_renderer 安全加固**：新增 crash_dir/cache_dir 隔离、显式 TEMP/TMP/TMPDIR 环境变量

## 待完成项

- [ ] **阶段三：全面重构 + RAG→SAG 升级** — 待启动
- [ ] **强化层 RL Skills 接入 Pipeline** — 需阶段三
- [ ] **上传患者资料与PDF处理闭环** — 执行方案已定（P0-P4），待开发
- [ ] **仪表盘启动脚本 GUI** — 当前需终端运行 run_dashboard.ps1

