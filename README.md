# MedAgent — 空白 Agent 框架（阶段一）

基于 LangGraph ReAct + FastAPI + React 的可复用多 Agent 协作平台。通过插件化 Skill 和流水线配置，快速部署到不同类型场景。当前为**空白框架**，流水线尚未注册 Skill，等待接入具体业务流程。

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangGraph ReAct |
| 后端 API | FastAPI + SSE 流式 |
| 前端 UI | React 19 + TypeScript + Ant Design 6 |
| 状态管理 | Zustand 5 |
| 图表 | ECharts 6 + echarts-for-react |
| 数学渲染 | KaTeX (react-markdown + rehype-katex) |
| 构建工具 | Vite 8 |
| 容器化 | Docker + docker compose |
| Python 包管理 | uv / pip (pyproject.toml) |

## 目录结构

```
MedAgent/
├── Code/
│   ├── main.py                   # 唯一主入口（web / cli / blank 三模式）
│   └── DataCode/                 # 后端模块（22 个 .py 文件）
│       ├── config_manager.py      # 平台配置（YAML 层级合并）
│       ├── tool_registry.py       # 工具注册与搜索
│       ├── builtin_tools.py       # 内置工具（文件读写、Memory、TODO）
│       ├── execute_tool.py        # 工具执行器（权限校验 + 日志）
│       ├── todo_manager.py        # 带状态的待办列表
│       ├── memory_store.py        # 短期 + 长期记忆存储
│       ├── context_manager.py     # Token 监控与上下文压缩
│       ├── deep_agent.py          # LangGraph ReAct Agent 工厂
│       ├── agent_manager.py       # Agent 生命周期管理（含子 Agent 调度）
│       ├── skill_parser.py        # SKILL.md YAML frontmatter 解析器
│       ├── skill_executor.py      # Skill 执行引擎（Tab 并行 + Pipeline 串行双模式）
│       ├── llm_callback.py        # LLM 调用跟踪与统计
│       ├── log_setup.py           # 日志配置
│       ├── knowledge_base.py      # 知识库抽象接口（RAGQuery）
│       ├── text_cleaner.py        # KB 结果文本清洗
│       ├── mcp_connector.py       # MCP 协议连接器
│       ├── execution_logger.py    # 三格式日志（JSON/MD/TXT）
│       ├── report_generator.py    # 报告生成器
│       ├── web_server.py          # FastAPI 应用工厂
│       └── web_routes/            # API 路由（5 个模块）
│           ├── patients.py        # 患者列表与文件读取
│           ├── chat.py            # SSE 流式对话
│           ├── reports.py         # 报告 CRUD 与下载
│           ├── kb.py              # 知识库查询
│           └── debug.py           # 调试接口
├── Data/                          # 平台配置与通用数据
│   ├── platform.yaml              # 平台配置（LLM、沙箱、缓存等）
│   ├── agents/                    # Agent 提示词配置
│   │   ├── main/                  # 主 Agent（系统提示词、可用工具/技能）
│   │   ├── main_agent/            # 备用 Agent 配置
│   │   └── hitl/                  # 人工审核（HITL）配置
│   ├── skills/                    # Skill 定义目录
│   │   └── pipeline.yaml          # 流水线配置（steps 为空，等待注册）
│   ├── knowledge_base/            # 知识库（按需填充，已创建空目录）
│   └── memory/                    # 长期记忆存储（运行后自动创建）
├── TempData/                      # 用户输入
│   ├── params.txt                 # 运行参数（两行格式）
│   └── patients/                  # 患者 PDF 数据（按需填充）
├── Result/                        # 分析结果输出
├── frontend/                      # React 前端
│   └── src/
│       ├── components/            # UI 组件
│       │   ├── TopBar/              # 顶部导航栏
│       │   ├── PatientList/         # 患者卡片列表 + 文件抽屉
│       │   ├── ChatPanel/           # AI 对话面板（SSE 流式）
│       │   ├── ReportPanel/         # 报告标签页（5 个 Tab）
│       │   │   ├── TabOverview.tsx    # 概况总览
│       │   │   ├── TabTreatment.tsx   # 治疗方案
│       │   │   ├── TabHistory.tsx     # 病史
│       │   │   ├── TabCare.tsx        # 随访/护理
│       │   │   └── TabPrediction.tsx  # 预测
│       │   └── common/              # 通用组件（MarkdownRenderer）
│       ├── store/                 # Zustand 状态管理
│       ├── hooks/useChat.ts       # SSE 连接管理
│       ├── services/api.ts        # API 客户端 + SSE 解析
│       └── types/index.ts         # TypeScript 类型定义
├── Docker/                        # 容器化部署
└── .env.example                   # 环境变量模板
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
# Linux / macOS
cp .env.example .env

# Windows
copy .env.example .env

# 编辑 .env 填入 API 密钥
```

支持的 LLM 供应商：DeepSeek（默认）、OpenAI、阿里云 DashScope。最少需配置 `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL`。

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e .
```

### 3. 运行空白验证

```bash
python Code/main.py blank
```

预期输出 9 项 PASS，确认框架就绪。

### 4. 启动 Web 服务

```bash
# 启动后端（终端 1）
python Code/main.py web

# 启动前端（终端 2）
cd frontend && npm install && npm run dev
```

前端 `http://localhost:3000/`，后端 `http://localhost:8000/`，Vite 自动代理 `/api` 到后端。

## 配置说明

### 平台配置 (`Data/platform.yaml`)

```yaml
llm:
  base_url: "https://api.deepseek.com/v1"
  api_key: "sk-your-api-key"
  api_format: "openai"
  default_model: "deepseek-v4-flash"
  temperature: 0.7
  context_length: 200000
  parallel_tool_calls: false

memory:
  max_short_term: 50
  long_term_path: "Data/memory/long_term"

context:
  summary_threshold: 0.7    # 触发摘要的阈值
  force_threshold: 0.9      # 强制压缩阈值
  keep_recent_turns: 5
  compression_buffer_tokens: 8000

sandbox:                     # 安全沙箱
  path_mode: "whitelist"
  shell_blacklist: ["rm -rf", "sudo", "chmod 777"]
  network_blacklist: ["10.0.0.0/8", "localhost"]

caching:
  enabled: true
  prompt_order: [system_prompt, memory, session_context, messages]

mcp_local:
  enabled: true
```

API Key 支持从 `.env` 环境变量读取（优先级高于 YAML），支持多候选自动切换。

### 运行参数 (`TempData/params.txt`)

两行格式（第一行参数名，第二行参数值）：

```
model
deepseek-chat
temperature
0.4
kb_top_k
15
```

### Agent 配置 (`Data/agents/`)

| 目录 | 说明 |
|------|------|
| `main/` | 主 Agent（系统提示词、可用工具、可用技能） |
| `main_agent/` | 备用 Agent 配置 |
| `hitl/` | 人工审核（Human-in-the-Loop）配置：Plan 审核开关、敏感操作列表 |

### 流水线配置 (`Data/skills/pipeline.yaml`)

```yaml
pipeline:
  mode: "report"       # "report"（串行报告）或 "pipeline"（通用流水线）
  steps: []            # 在此注册 Skill，例如：
  # - name: "01-data-organization"
  #   display_name: "资料整理"
  #   skill_file: "01-data-organization/SKILL.md"
```

## API 接口一览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/patients` | GET | 患者列表 |
| `/api/patients/{id}/files` | GET | 患者文件列表 |
| `/api/patients/{id}/files/{file}` | GET | 读取单个文件内容 |
| `/api/chat/{patient_id}` | GET (SSE) | 流式对话 |
| `/api/reports/{patient_id}` | GET | 获取报告 |
| `/api/reports/{patient_id}` | POST | 保存/更新报告 |
| `/api/reports/{patient_id}` | PUT | 编辑报告 |
| `/api/reports/{patient_id}/download` | GET | 下载报告 PDF |
| `/api/kb/query` | POST | 知识库查询 |
| `/api/kb/status` | GET | 知识库状态 |

## 如何接入业务 Skill

1. 在 `Data/skills/` 下创建 Skill 目录，放入 `SKILL.md`（YAML frontmatter + Markdown body）
2. 在 `Data/skills/pipeline.yaml` 的 `steps` 中注册该 Skill
3. Skill 引擎支持两种执行模式：
   - **Tab 并行**：多个独立 Skill 同时执行（默认报告 Tab 模式）
   - **Pipeline 串行**：按步骤顺序执行，上一步输出作为下一步输入
4. 结果通过 SSE 推送到前端，自动渲染到对应 Tab

### SKILL.md 结构

每个 Skill 包含：名称、描述、执行模式、子 Skill 列表、系统提示词、知识库引用、错误处理规则、可用工具声明。

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_API_KEY` | 是 | - | 通用 LLM API 密钥 |
| `LLM_BASE_URL` | 是 | - | LLM 服务地址 |
| `LLM_MODEL` | 是 | - | 模型名称 |
| `LLM_PROVIDER` | 否 | `DEEPSEEK` | 供应商选择，影响候选排序 |
| `DEEPSEEK_API_KEY` | 否 | - | DeepSeek 专用密钥 |
| `OPENAI_API_KEY` | 否 | - | OpenAI 备用密钥 |
| `DASHSCOPE_API_KEY` | 否 | - | 阿里云 DashScope 备用密钥 |
| `PORT` | 否 | `8000` | 后端服务端口 |

## 测试

```bash
# 空白验证（检查框架是否就绪）
python Code/main.py blank

# Web 模式启动后，测试 API
curl http://localhost:8000/api/patients

# 前端格式检查
cd frontend && npx eslint .
```

## Docker 部署

前置要求：Docker 24+、Docker Compose V2。

```bash
# 1. 配置环境变量
copy .env.example .env

# 2. 构建并启动
docker compose -f Docker/docker-compose.yaml --env-file .env up --build

# 或使用辅助脚本（Linux/macOS）
bash Docker/start.sh
```

> Windows 用户请使用 PowerShell 执行 `docker compose` 命令，或安装 WSL2 后运行 `bash Docker/start.sh`。

## 安全设计

- **路径白名单**：Agent 只能读写 `TempData/`、`Result/`、`Data/` 下的白名单路径
- **文件大小限制**：读写操作 10MB 上限
- **Session ID 验证**：格式 `YYYY-MM-DD_HHMMSS_<6位hex>`，防止路径遍历
- **API Key 管理**：支持 `.env` 环境变量覆盖 YAML 明文配置，多候选自动切换
- **沙箱隔离**：Shell 黑名单（禁止 `rm -rf`、`sudo` 等） + 网络黑名单（禁止内网访问）
- **人工审核（HITL）**：支持 Plan 审核开关和敏感操作列表配置
- **LLM 容错**：认证失败/超时自动切换候选模型

## 当前状态

- **阶段一（进行中）**：空白 Agent 框架已提取完成，9 项验证全部通过
- **流水线**：`pipeline.yaml` 的 `steps` 为空，无 Skill 注册
- **知识库**：`Data/knowledge_base/` 为空，等待填充
- **测试数据**：`TempData/patients/张三-001/` 已导入 490 个文件（21 PDF + OCR 中间文件）

## 许可证

MIT
