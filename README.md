# MedAgent — 肺癌慢病化管理 AI 门诊系统

基于 LangGraph ReAct + FastAPI + React 构建的 AI 医生助手，专为肺癌慢病化管理场景设计。通过 10 步 Agent 流水线自动分析患者 PDF 病历资料，输出结构化门诊报告。

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangGraph ReAct + 隔离子 Agent 并行调度 |
| 后端 API | FastAPI + SSE 流式 |
| 向量检索 | ChromaDB + BAAI/bge-small-zh-v1.5 |
| 知识库 | 127 份医学指南/共识 |
| 前端 UI | React 19 + TypeScript + Ant Design 6 |
| 状态管理 | Zustand 5 |
| 图表 | ECharts 6 + echarts-for-react |
| 报告生成 | Markdown / HTML / PDF (fpdf2) |
| 构建工具 | Vite 8 |
| 容器化 | Docker + docker compose |
| Python 管理 | uv / pip (pyproject.toml) |

## 功能特性

- **PDF 智能解析**：自动 OCR 提取患者病历资料（影像/检验/病理/病历/医生诊疗）
- **10 步 Agent 流水线**：资料整理 → 预处理 → 场景判断 → 病史总结 → 患者概况 → 治疗方案 → 疗效预测 → 其他建议 → 报告生成
- **子 Agent 并行加速**：多子任务并行执行，总耗时从 44 分钟优化至 3-5 分钟
- **RAG 知识库检索**：基于 ChromaDB 的语义检索，支持 NCCN/CSCO/ESMO/ASCO 等权威指南引用
- **就诊范围选择**：支持按就诊时间筛选，生成单次或综合报告
- **5 个结构化的报告标签页**：患者病史、患者概况、治疗方案、疗效预测、其他建议
- **证据等级标注**：每条引用标注来源及证据等级（国际指南 / 国内指南 / 专家共识等）
- **多 LLM 候选容灾**：多个 API Key 自动切换，认证失败/超时自动降级
- **SSE 流式推送**：前端实时更新报告进度，支持运行时序图可视化

## 目录结构

```
MedAgent/
├── Code/
│   ├── main.py                        # 唯一主入口（web / cli / blank）
│   └── DataCode/                      # 后端核心模块
│       ├── agent_manager.py           # Agent 生命周期管理（主 Agent + 子 Agent 并行调度）
│       ├── skill_executor.py          # 流水线执行引擎（快速模式 / 完整模式）
│       ├── knowledge_base.py          # RAG 知识库抽象接口 + 证据等级映射
│       ├── deep_agent.py              # LangGraph ReAct Agent 工厂
│       ├── builtin_tools.py           # 内置工具（rag_query / batch_pdf_to_md / 文件读写等）
│       ├── report_generator.py        # MD/HTML/PDF 三格式报告生成
│       ├── tool_registry.py           # 工具注册与搜索
│       ├── execute_tool.py            # 工具执行器（权限校验 + 日志）
│       ├── skill_parser.py            # SKILL.md YAML frontmatter 解析器
│       ├── config_manager.py          # 平台配置（YAML 层级合并）
│       ├── context_manager.py         # Token 监控与上下文压缩
│       ├── memory_store.py            # 短期 + 长期记忆存储
│       ├── todo_manager.py            # 待办列表管理
│       ├── llm_callback.py            # LLM 调用跟踪与统计
│       ├── text_cleaner.py            # KB 结果文本清洗
│       ├── pdf_ocr.py                 # PDF OCR 预处理（pypdfium2 + easyocr）
│       ├── mcp_connector.py           # MCP 协议连接器
│       ├── execution_logger.py        # 三格式日志
│       ├── web_server.py              # FastAPI 应用工厂
│       ├── _shared.py                 # 共享模块（env 加载、LLM 候选构建）
│       ├── scripts/                   # 辅助脚本
│       └── web_routes/                # API 路由
│           ├── patients.py            # 患者列表 + 文件读取 + 就诊分组
│           ├── chat.py                # SSE 流式对话 + 就诊过滤
│           ├── reports.py             # 报告 CRUD + PDF 下载
│           ├── kb.py                  # 知识库查询/状态
│           └── debug.py               # 调试接口 + Pipeline 历史查询
├── Data/
│   ├── platform.yaml                  # LLM / 证据映射 / 安全沙箱配置
│   ├── agents/                        # Agent 提示词配置
│   │   ├── main/                      # 主 Agent
│   │   ├── main_agent/                # 备用配置
│   │   └── hitl/                      # 人工审核配置
│   ├── skills/                        # 40+ Skill 定义（10 应用层 + 5 强化层 + 共享）
│   │   ├── pipeline.yaml             # 10 步流水线配置
│   │   ├── 01-data-organization/     # 资料整理
│   │   ├── 02-data-preprocessing/    # PDF转换 + OCR双路径
│   │   ├── 03-loop-count-determination/ # 就诊循环分析
│   │   ├── 04-scenario-judgment/     # 初诊/复诊/转诊判断
│   │   ├── 05-patient-history-summary/ # 五史并行提取
│   │   ├── 06-patient-profile/       # 7子Agent并行评估
│   │   ├── 07-treatment-plan/        # 指南匹配 + 方案评估
│   │   ├── 08-efficacy-prediction/   # 疗效 + 不良反应预测
│   │   ├── 09-other-suggestions/     # 康复/护理/随访建议
│   │   ├── 10-report-generation/     # 报告本地汇总
│   │   ├── _shared/knowledge-retrieval/ # RAG 共享检索
│   │   └── rl-*/                     # 5 强化层 Skill（模型微调 + 经验学习）
│   ├── knowledge_base/
│   │   ├── tool.py                   # ChromaDB 语义检索 + 年份/来源提取
│   │   └── chroma_db/               # 向量知识库（259MB，121 PDF，29013 文档块）
│   └── memory/                       # 长期记忆
├── TempData/
│   ├── params.txt                    # 运行参数
│   └── patients/                     # 患者 PDF 数据
│       ├── 张三-001/                 # 21 份 PDF（标准测试用例）
│       ├── 李四-002/                 # 9 份 PDF
│       ├── 王五-003/                 # 17 份 PDF
│       └── 刘海平-004/               # 100 份 PDF（5 类资料全覆盖）
├── Result/                           # 报告输出 + Pipeline 日志
├── frontend/                         # React 19 前端
│   └── src/
│       ├── components/
│       │   ├── ChatPanel/            # SSE 流式对话 + 就诊选择 + 快捷操作
│       │   ├── ReportPanel/          # 5 Tab 报告面板 + Pipeline 时序图
│       │   │   ├── TabHistory.tsx      # 患者病史
│       │   │   ├── TabOverview.tsx     # 患者概况（含 ECharts 图表）
│       │   │   ├── TabTreatment.tsx    # 治疗方案
│       │   │   ├── TabPrediction.tsx   # 疗效预测（趋势图/生存曲线）
│       │   │   ├── TabCare.tsx         # 随访护理建议
│       │   │   └── PipelineTiming.tsx  # 运行耗时瀑布图
│       │   ├── PatientList/          # 患者卡片 + 文件抽屉
│       │   └── common/               # MarkdownRenderer / ErrorBoundary
│       ├── store/                    # Zustand 状态管理
│       ├── hooks/useChat.ts          # SSE 连接管理
│       └── services/api.ts           # API 客户端
├── Docker/                           # 容器化部署
└── .env.example                      # 环境变量模板
```

## 三种运行模式

| 模式 | 命令 | 功能 |
|------|------|------|
| `web` | `python Code/main.py web` | 启动 FastAPI 服务（端口 8000）+ 前端交互 |
| `cli` | `python Code/main.py cli` | 命令行流水线，读 `TempData/params.txt` 串行执行 |
| `blank` | `python Code/main.py blank` | 空白验证：9 项检查确认框架可用 |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- LLM API Key（在 `.env` 中配置）

### 1. 配置环境变量

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env

# 编辑 .env 填入 API 密钥
```

支持的 LLM 供应商：DeepSeek（默认）、OpenAI、阿里云 DashScope。最少需配置 `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL`。

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e .
```

### 3. 安装知识库依赖

```bash
pip install chromadb sentence-transformers
```

首次启动时会自动下载嵌入模型（BAAI/bge-small-zh-v1.5，约 30MB）。

### 4. 运行空白验证

```bash
python Code/main.py blank
```

预期输出 9 项 PASS，确认框架就绪。

### 5. 启动 Web 服务

```bash
# 启动后端（终端 1）
python Code/main.py web

# 启动前端（终端 2）
cd frontend && npm install && npm run dev
```

前端 `http://localhost:3000/`，后端 `http://localhost:8000/`，Vite 自动代理 `/api` 到后端。

## 使用流程

1. 打开浏览器进入 `http://localhost:3000`
2. 从左侧患者列表选择一个患者（张三/李四/王五/刘海平）
3. 可选：在顶部选择就诊范围（「全部就诊」或单次入院）
4. 点击「生成报告」按钮
5. 等待 3-5 分钟，系统自动完成 10 步分析
6. 右侧 5 个标签页实时更新，完成后可下载 PDF 报告

## 报告内容

| 标签页 | 内容 | 数据来源 |
|--------|------|---------|
| 患者病史 | 现病史时间线、既往史、过敏史、个人史、家族史 | 5 个子 Agent 并行提取 |
| 患者概况 | 主诉、体格检查、TNM分期、疗效评估、不良反应、合并症、ECOG评分 | 7 个子 Agent + RAG检索 |
| 治疗方案 | 多方案排序、决策路径、临床试验筛选、不良反应管理 | RAG 指南匹配 + 专家共识 |
| 疗效预测 | ORR/PFS/OS 预测、肿瘤趋势图、生存曲线、不良反应预测 | 3 个子 Agent 并行 |
| 其他建议 | 康复指导、护理措施、健康教育、随访计划、MDT建议 | 3 个子 Agent 并行 |

## 性能优化历程

| 版本 | 总耗时 | 关键改进 |
|------|--------|---------|
| V2.0 基线 | 44.6 分钟 | 串行子 Agent + 全量上下文注入 |
| V2.1 轻量瘦身 | ~25 分钟 | 步骤感知预算、KB 跳过、递归上限调优 |
| V2.2 子Agent并行化 | ~15 分钟 | 4 个步骤内子任务并行执行 |
| V2.4 快速模式 | **3-5 分钟** | 跳过内部步骤 + 第10步本地汇总 + RAG直通 |

## 知识库

- **向量数据库**：ChromaDB（`Data/knowledge_base/chroma_db/`）
- **嵌入模型**：BAAI/bge-small-zh-v1.5（384 维）
- **文档规模**：121 份 PDF，29,013 个文档块
- **内容覆盖**：
  - 国际指南：NCCN（NSCLC/SCLC）、ESMO、ASCO
  - 国内指南：CSCO 肺癌诊疗指南
  - 分期标准：TNM 第九版、iRECIST
  - 不良反应：CTCAE 6.0 标准
  - 专家共识：中国肺癌专家共识 30+ 份
- **证据等级**：8 级映射（国际指南→国内指南→专家共识→RCT→真实世界研究→病例报告→专家意见）

### 扩建知识库

如需添加新的医学指南/PDF 到知识库：

```bash
cd 更新/folder-rag/folder-rag
pip install -r requirements.txt
python scripts/run_index.py --folder "D:\新PDF目录" --force
# 将生成的 database/chroma_db/ 复制到 MedAgentNEW/Data/knowledge_base/
```

## API 接口一览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/patients` | GET | 患者列表（含就诊分组） |
| `/api/patients/{id}/files` | GET | 患者文件列表 |
| `/api/chat/{patient_id}` | GET (SSE) | 流式对话 + 报告生成 |
| `/api/reports/{patient_id}` | GET | 获取报告 |
| `/api/reports/{patient_id}/download` | GET | 下载报告（MD/HTML/PDF） |
| `/api/kb/query` | POST | 知识库语义查询 |
| `/api/kb/trace` | POST | 知识库追溯查询（含患者资料） |
| `/api/kb/status` | GET | 知识库状态（文档数/模型/版本） |
| `/api/debug/llm` | GET | LLM 配置状态 |
| `/api/debug/llm/health` | GET | LLM 连接健康检查 |
| `/api/debug/pipeline` | GET | Pipeline 运行历史 |

## 配置说明

### 平台配置 (`Data/platform.yaml`)

```yaml
llm:
  base_url: "https://api.deepseek.com/v1"
  api_key: "sk-your-api-key"
  default_model: "deepseek-v4-flash"
  temperature: 0.7
  context_length: 200000
  parallel_tool_calls: true

evidence_mapping:             # 证据等级映射
  NCCN: "international_guideline"   # 7 分
  CSCO: "national_guideline"        # 6 分
  ESMO: "international_guideline"   # 7 分
  ASCO: "international_guideline"   # 7 分
  SITC: "international_consensus"   # 5 分
  CTCAE: "international_guideline"  # 7 分
  # ... 共 21 个映射项
```

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_API_KEY` | 是 | - | 通用 LLM API 密钥 |
| `LLM_BASE_URL` | 是 | - | LLM 服务地址 |
| `LLM_MODEL` | 是 | - | 模型名称 |
| `LLM_PROVIDER` | 否 | `DEEPSEEK` | 供应商选择 |
| `DEEPSEEK_API_KEY` | 否 | - | DeepSeek 备用密钥 |
| `OPENAI_API_KEY` | 否 | - | OpenAI 备用密钥 |
| `PORT` | 否 | `8000` | 后端服务端口 |

## 当前状态

- **阶段一（框架提取）**：✅ 完成 — 空白 Agent 框架提取，硬编码全量清零
- **阶段二（肺癌医生流程集成）**：✅ 完成 — 10 步 Pipeline + 40+ Skill + ChromaDB 知识库
  - V2.0-V2.4 共 20+ 轮迭代优化
  - 报告生成 44 分钟 → **3-5 分钟**
  - 支持张三/李四/王五/刘海平 4 患者测试验证
- **阶段三（全面重构 + RAG→SAG 升级）**：📋 待开始

## 安全设计

- **路径白名单**：Agent 只能读写 `TempData/`、`Result/`、`Data/` 下的白名单路径
- **文件大小限制**：读写操作 10MB 上限
- **API Key 管理**：支持 `.env` 环境变量覆盖 YAML 明文配置，多候选自动切换
- **沙箱隔离**：Shell 黑名单 + 网络黑名单
- **LLM 容错**：认证失败/超时自动切换候选模型，单步失败不连锁阻断后续步骤
- **子 Agent 保护**：120s 超时 + recursion_limit=25 防止卡死

## 许可证

MIT
