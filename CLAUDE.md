# MedAgent — 肺癌慢病化管理 AI 门诊系统

## 项目概述

基于 LangGraph ReAct + FastAPI + React 构建的 AI 医生助手。通过 10 步 Agent 流水线自动分析患者 PDF 病历资料，结合 ChromaDB 医学知识库检索，输出 5 个 Tab 的结构化门诊报告（患者病史/概况/治疗方案/疗效预测/其他建议）。

---

## Karpathy 编码准则

> 源自 Andrej Karpathy 对 LLM 常见编程错误的观察。减少不必要的改动、过度工程化和隐含假设。
> **权衡**：这些准则偏向谨慎而非速度。对简单任务可酌情放宽。

### 1. Think Before Coding

**不要假设。不要隐藏困惑。暴露权衡。**

实施之前：
- 明确陈述你的假设。如果不确定，先问。
- 如果有多种解释，提出来——不要默默选择其中一个。
- 如果有更简单的方案，说出来。在必要时敢于反驳。
- 如果有不清楚的地方，停下来。说出困惑，然后提问。

### 2. Simplicity First

**用最少的代码解决问题。不做投机性开发。**

- 不做超出需求的特性。
- 不为只用一次的逻辑建抽象层。
- 不添加没被要求的"灵活性"或"可配置性"。
- 不处理不可能发生的错误场景。
- 如果写了 200 行但只需 50 行，重写。

问自己："高级工程师会觉得这个过于复杂吗？" 如果是，简化。

### 3. Surgical Changes

**只动必须动的地方。只清理自己留下的混乱。**

编辑现有代码时：
- 不要"顺手改进"旁边的代码、注释或格式。
- 不要重构没坏的代码。
- 匹配现有风格，即使你习惯不同的写法。
- 如果发现无关的死代码，提出来——但不要删掉。

当你的改动产生了孤儿代码：
- 删除由**你的改动**导致的未使用的导入/变量/函数。
- 不要删除本就存在的死代码，除非被要求。

检验标准：每行改动都应能直接追溯到用户的需求。

### 4. Goal-Driven Execution

**定义成功标准。循环直到验证通过。**

将任务转化为可验证的目标：
- "加验证" → "为无效输入写测试，然后让它们通过"
- "修 bug" → "写一个能复现 bug 的测试，然后让测试通过"
- "重构 X" → "确保测试在重构前后都通过"

对于多步任务，简述计划：
1. [步骤] → 验证：[检查项]
2. [步骤] → 验证：[检查项]
3. [步骤] → 验证：[检查项]

强有力的成功标准让你能独立迭代循环。薄弱的标准（"让它能跑"）需要不断澄清。

**这些准则生效的标志是：** diff 中不必要的变更更少，因过度工程化导致的返工更少，澄清性问题出现在实施之前而非犯错之后。

---

## 目录结构

```
MedAgent/
├── Code/
│   ├── main.py                        # 唯一主入口（web / cli / blank）
│   └── DataCode/                      # 后端核心模块
│       ├── agent_manager.py           # Agent 生命周期 + 子Agent并行调度
│       ├── skill_executor.py          # 流水线执行引擎 + LLM多候选路由
│       ├── knowledge_base.py          # RAG知识库抽象 + 证据等级映射
│       ├── deep_agent.py              # LangGraph ReAct Agent 工厂
│       ├── builtin_tools.py           # 内置工具（rag_query, batch_pdf_to_md等）
│       ├── report_generator.py        # MD/HTML/PDF 三格式报告
│       ├── tool_registry.py           # 工具注册与搜索
│       ├── skill_parser.py            # SKILL.md 解析器
│       ├── config_manager.py          # YAML 层级配置管理
│       ├── context_manager.py         # Token 监控与上下文压缩
│       ├── memory_store.py            # 短期+长期记忆
│       ├── text_cleaner.py            # KB 结果文本清洗
│       ├── pdf_ocr.py                 # PDF OCR 预处理
│       ├── mcp_connector.py           # MCP 协议连接器
│       ├── execution_logger.py        # 三格式日志
│       ├── web_server.py              # FastAPI 应用工厂
│       ├── _shared.py                 # 共享模块（env加载, LLM候选构建）
│       └── web_routes/                # API 路由（5个模块）
│           ├── patients.py            # 患者列表+就诊分组
│           ├── chat.py                # SSE 流式对话+就诊过滤
│           ├── reports.py             # 报告 CRUD+PDF下载
│           ├── kb.py                  # 知识库查询
│           └── debug.py               # 调试接口
├── Data/
│   ├── platform.yaml                  # 平台配置（LLM, 证据映射, 安全沙箱）
│   ├── agents/main/                   # Agent 提示词配置
│   ├── skills/                        # 40+ Skill定义
│   │   ├── pipeline.yaml             # 10步流水线配置
│   │   ├── 01-data-organization/     # 资料整理
│   │   ├── 02-data-preprocessing/    # 资料预处理
│   │   ├── 03-loop-count-determination/ # 就诊循环分析
│   │   ├── 04-scenario-judgment/     # 场景判断
│   │   ├── 05-patient-history-summary/ # 病史总结（5子Agent并行）
│   │   ├── 06-patient-profile/       # 患者概况（7子Agent+RAG）
│   │   ├── 07-treatment-plan/        # 治疗方案（指南匹配）
│   │   ├── 08-efficacy-prediction/   # 疗效预测
│   │   ├── 09-other-suggestions/     # 其他建议
│   │   ├── 10-report-generation/     # 报告本地汇总
│   │   ├── _shared/knowledge-retrieval/ # RAG共享检索
│   │   └── rl-*/                     # 5个强化层Skill
│   ├── knowledge_base/
│   │   ├── tool.py                   # ChromaDB语义检索
│   │   └── chroma_db/                # 向量知识库（构建产物）
│   └── memory/
├── TempData/
│   ├── params.txt                    # CLI运行参数
│   └── patients/                     # 患者PDF数据
├── Result/                           # 报告输出
├── frontend/                         # React 19 前端
├── Docker/                           # 容器化部署
├── .env                              # API密钥等环境变量
├── pyproject.toml
└── .gitignore
```

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangGraph ReAct + 隔离子Agent并行调度 |
| 后端 API | FastAPI + SSE 流式 |
| 向量检索 | ChromaDB + Ollama bge-m3 embedding；可选本地 CrossEncoder reranker |
| 知识库规模 | 已索引文档 365，文档块 44307 |
| 前端 UI | React 19 + TypeScript + Ant Design 6 |
| 状态管理 | Zustand 5 |
| 图表 | ECharts 6 |
| 报告生成 | Markdown / HTML / PDF；PDF 优先 V4 HTML/CSS + Edge/Chrome 打印，失败回退 fpdf2 |
| 容器化 | Docker + docker compose |

## 代码规范

### 命名规范
| 类型 | 规范 | 示例 |
|------|------|------|
| Python 文件/模块 | `snake_case` | `skill_executor.py`, `tool_registry.py` |
| Python 类 | `PascalCase` | `RagKnowledgeBase`, `SkillExecutor` |
| Python 函数/方法 | `snake_case` | `_run_skill_via_agent()`, `_format_knowledge()` |
| Python 变量 | `snake_case` | `knowledge_results`, `prev_summary` |
| Python 常量 | `UPPER_SNAKE_CASE` | `LLM_TAB_TIMEOUT_SECONDS`, `SKILL_RECURSION_LIMIT` |
| Python 私有方法/变量 | `_前置下划线` | `_ensure_init()`, `_query_cache` |
| TypeScript/前端 | `camelCase` + `PascalCase(组件)` | `useChat.ts`, `ReportPanel/index.tsx` |
| 配置文件 | `snake_case` | `platform.yaml`, `pipeline.yaml` |
| 环境变量 | `UPPER_SNAKE_CASE` | `LLM_API_KEY`, `MEDAGENT_FULL_PIPELINE` |
| 输出文件（对外） | `PascalCase` | `AIDiagnosisReport.pdf` |
| 输出文件（内部） | `snake_case` | `errors.json`, `pipeline_summary.json` |

### 代码风格
- **类型注解**：所有函数参数和返回值必须标注类型（Python 3.10+）
  ```python
  async def query(self, question: str, top_k: int = 3) -> list[KnowledgeResult]:
  ```
- **文档字符串**：函数/类必须有 docstring，说明参数和返回值
- **日志**：使用 `import logging; logger = logging.getLogger(__name__)`，不用 print
- **异步**：IO密集型操作用 `async/await`，CPU密集型用 `asyncio.to_thread()`
- **错误处理**：自定义异常类，外层统一捕获；LLM错误分类使用 `_classify_llm_error()`
- **配置驱动**：所有可变参数从 `platform.yaml` 或 `params.txt` 读取，禁止硬编码

### 代码铁律
| # | 规则 | 说明 |
|---|------|------|
| 1 | 代码位置 | 业务逻辑只在 `Code/DataCode/` 下，主入口仅 `Code/main.py` |
| 2 | 参数传递 | 通过 `tempdata/params.txt`（两行格式），**禁止**命令行参数 |
| 3 | 无硬编码 | 路径、样本名、癌种、参数值必须可配置 |
| 4 | 温度隔离 | 报告用 `llm.temperature`，对话用 `llm.chat_temperature` |
| 5 | LLM客户端复用 | 通过 `_get_or_create_llm()` 缓存，不重复创建 |
| 6 | 子Agent保护 | 必须设置 `recursion_limit` + `asyncio.wait_for()` 超时 |
| 7 | 配置文件 | YAML 配置用 `ConfigManager.get("key.subkey")` 读取 |
| 8 | 文件读写 | 路径白名单：`TempData/`, `Result/`, `Data/`；大小限制10MB |

## 关键架构约束

### 温度配置（双温度隔离）
- **报告生成**（Pipeline 05-10 + 所有Agent/子Agent）：`llm.temperature = 0`
- **医生对话**（SSE流式聊天）：`llm.chat_temperature = 0.1`
- 配置入口唯一：`Data/platform.yaml`
- 代码运行时读取方式：`config.get("llm.chat_temperature", config.get("llm.temperature", 0.7))`

### 流水线执行模式
- 默认**快速报告模式**：OCR已加载时跳过01-04内部步骤，第10步本地汇总
- 完整模式：设置环境变量 `MEDAGENT_FULL_PIPELINE=1`
- 步骤依赖链（`_PREV_STEP_DEPS`）：05→02, 06→05, 07→05+06, 08→05-07, 09→05-08, 10→05-09
- 子Agent并行化：05/06/07/08 步骤内使用 `sessions_spawn_parallel`

### 递归上限（按步骤分级）
```python
01: 60 | 02: 60 | 03: 60 | 04: 100 | 05: 80
06: 100 | 07: 80 | 08: 80 | 09: 80 | 10: 60
```

### 知识库
- **仅查询**：`Data/knowledge_base/tool.py` + `knowledge_base.py`
- **建库**：需使用 `更新/folder-rag/folder-rag/scripts/run_index.py`
- 当前索引使用 Ollama `bge-m3` embedding；默认快速向量召回，不启用 CrossEncoder
- 设置 `KB_ENABLE_RERANKER=1` 时才启用本地 `BAAI/bge-reranker-v2-m3` 精排
- 报告生成默认 `MEDAGENT_KB_TOP_K=8`，减少提示词注入和生成耗时
- 证据等级映射在 `Data/platform.yaml` 的 `evidence_mapping` 中管理

### PDF 导出
- PDF 优先调用 `Code/DataCode/reporting/pdf_renderer_v4.py`，使用 V4 HTML/CSS 模板和本机 Edge/Chrome 打印。
- 当前本机 Edge 路径：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
- Edge Headless 需要纯英文、当前用户可写的临时目录：
  - `MEDAGENT_PDF_TMP_DIR=C:\medagent_tmp\edge_pdf`
  - `MEDAGENT_CHROMIUM_PATH=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
- `setx` 写入用户环境变量后，已运行后端不会自动读取，必须重启后端。

## 运行方式

```bash
# 空白验证
python Code/main.py blank

# Web服务（后端）
python Code/main.py web

# CLI流水线（读 params.txt）
python Code/main.py cli

# 前端（另一个终端）
cd frontend && npm install && npm run dev
```

PowerShell 启动后端前可显式带上 PDF 环境变量：

```powershell
$env:MEDAGENT_PDF_TMP_DIR="C:\medagent_tmp\edge_pdf"
$env:MEDAGENT_CHROMIUM_PATH="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
python Code/main.py web
```

## 测试

- 测试患者：张三-001(21份)、李四-002(9份)、王五-003(17份)、刘海平-004(100份)
- 验证命令：`python Code/main.py blank`（9项检查）
- 知识库验证：`curl http://localhost:8000/api/kb/status`

## 关键文件

| 文件 | 用途 |
|------|------|
| `Data/platform.yaml` | LLM配置、证据映射（唯一温度入口） |
| `Data/skills/pipeline.yaml` | 10步流水线定义 |
| `Code/DataCode/skill_executor.py` | 流水线引擎 + 快速模式逻辑 |
| `Code/DataCode/agent_manager.py` | Agent调度 + 子Agent并行 + LLM缓存 |
| `Data/knowledge_base/tool.py` | ChromaDB语义检索 |
| `Code/DataCode/report_context.py` | 跨时间段连续报告上下文读写 |
| `Code/DataCode/reporting/` | V4 报告 HTML/PDF 模板、归一化和浏览器渲染 |
| `迭代记录.md` | 全量开发迭代日志（当前至 V3.5） |
| `project_memory.md` | 项目记忆和上下文 |
