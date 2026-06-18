# MedAgent — 空白 Agent 框架（阶段一）

基于 LangGraph + FastAPI + React 的可复用 Agent 框架。通过插件化 Skill 和流水线配置，快速部署到不同类型场景。当前为**空白框架**，流水线尚未注册 Skill，等待接入具体业务流程。

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangGraph (DeepAgents) |
| 后端 API | FastAPI + SSE |
| 前端 UI | React 19 + TypeScript + Ant Design 6 |
| 状态管理 | Zustand 5 |
| 图表 | ECharts 6 |
| 构建工具 | Vite 8 |
| 容器化 | Docker + docker-compose |
| 包管理 | uv (Python), npm (Node) |

## 目录结构

```
MedAgent/
├── Code/
│   ├── main.py                   # 唯一主入口（web / cli / blank 三模式）
│   └── DataCode/                 # 后端模块（20 个）
│       ├── config_manager.py      # 平台配置（YAML + TXT）
│       ├── tool_registry.py       # 工具注册与搜索
│       ├── builtin_tools.py       # 内置工具（文件读写、Memory、TODO）
│       ├── execute_tool.py        # 工具执行器（权限 + 日志）
│       ├── todo_manager.py        # 带状态的待办列表
│       ├── memory_store.py        # 记忆存储（短期 + 长期）
│       ├── context_manager.py     # Token 监控与压缩
│       ├── deep_agent.py          # LangGraph ReAct Agent 工厂
│       ├── agent_manager.py       # Agent 生命周期管理
│       ├── skill_parser.py        # SKILL.md 解析器
│       ├── skill_executor.py      # Skill 执行引擎（Tab + Pipeline 模式）
│       ├── knowledge_base.py      # 知识库抽象接口
│       ├── mcp_connector.py       # MCP 连接器
│       ├── execution_logger.py    # 三格式日志（JSON/MD/TXT）
│       ├── report_generator.py    # 报告生成器
│       ├── web_server.py          # FastAPI 应用工厂
│       └── web_routes/            # API 路由
│           ├── patients.py          # 患者列表与文件读取
│           ├── chat.py              # SSE 流式对话
│           ├── reports.py           # 报告 CRUD 与下载
│           ├── kb.py                # 知识库查询
│           └── debug.py             # 调试接口
├── data/
│   ├── platform.yaml              # 平台配置
│   ├── agents/main/               # Agent 配置（系统提示词、可用工具/技能）
│   ├── skills/                    # Skill 定义目录
│   │   └── pipeline.yaml           # 流水线配置（steps 为空，等待注册）
│   └── knowledge_base/            # 知识库（按需填充）
├── tempdata/
│   ├── params.txt                 # 运行参数（两行格式）
│   └── patients/                  # 输入数据（按需填充）
├── Result/                        # 分析结果输出（按 session 分目录）
├── frontend/                      # React 前端（完整保留）
│   └── src/
│       ├── components/            # UI 组件
│       │   ├── TopBar/              # 顶部导航栏
│       │   ├── PatientList/         # 患者卡片列表 + 文件抽屉
│       │   ├── ChatPanel/           # AI 对话面板（SSE 流式）
│       │   ├── ReportPanel/         # 报告标签页面板
│       │   └── common/              # 通用组件（MarkdownRenderer）
│       ├── store/                 # Zustand stores
│       ├── hooks/useChat.ts       # SSE 连接管理
│       ├── services/api.ts        # API 客户端 + SSE 解析
│       └── types/index.ts         # TypeScript 类型定义
├── Docker/                        # 容器化部署
└── tests/                         # 后端测试
```

## 三种运行模式

| 模式 | 命令 | 功能 |
|------|------|------|
| `web` | `python Code/main.py web` | 启动 FastAPI 服务（端口 8000）+ 前端交互 |
| `cli` | `python Code/main.py cli` | 命令行流水线，读 `tempdata/params.txt` 串行执行 |
| `blank` | `python Code/main.py blank` | 空白验证：9 项检查确认框架可用 |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- LLM API Key（在 `.env` 中配置）

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入 API 密钥
```

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

### 平台配置 (`data/platform.yaml`)

```yaml
llm:
  base_url: "https://api.deepseek.com/v1"
  api_key: "sk-your-api-key"
  default_model: "deepseek-v4-flash"
  context_length: 200000

memory:
  max_short_term: 50

context:
  summary_threshold: 0.7
  force_threshold: 0.9
  keep_recent_turns: 5
```

API Key 同时支持从 `.env` 读取，优先级高于 YAML。

### 运行参数 (`tempdata/params.txt`)

两行格式（第一行参数名，第二行参数值）：

```
model
deepseek-chat

temperature
0.4

pipeline_mode
pipeline

patient_id
demo
```

### Agent 配置 (`data/agents/main/`)

- `系统提示词.txt` — Agent 的系统 prompt
- `可用工具.txt` — 可用工具列表
- `可用技能.txt` — 可用技能列表

### 流水线配置 (`data/skills/pipeline.yaml`)

```yaml
pipeline:
  mode: "pipeline"
  steps: []   # 在此注册 Skill，例如：
  # - name: "my-skill"
  #   display_name: "我的技能"
  #   skill_file: "my-skill/SKILL.md"
```

## 如何接入业务 Skill

1. 在 `data/skills/` 下创建 Skill 目录，放入 `SKILL.md`（YAML frontmatter + Markdown body）
2. 在 `data/skills/pipeline.yaml` 的 `steps` 中注册该 Skill
3. Skill 引擎自动按序执行，结果通过 SSE 推送到前端

## 测试

```bash
# 空白验证
python Code/main.py blank

# Web 模式启动后，用 curl 测试 API
curl http://localhost:8000/api/patients

# 前端测试
cd frontend && npx vitest run
```

## Docker 部署

```bash
cp .env.example .env
bash Docker/start.sh
```

## 安全设计

- **路径白名单**：Agent 只能写入 `Result/` 和 `data/memory/`
- **文件大小限制**：读写操作 10MB 上限
- **Session ID 验证**：格式 `YYYY-MM-DD_HHMMSS_<6位hex>`，防止路径遍历
- **API Key**：支持 `.env` 环境变量覆盖 YAML 明文配置

## 当前状态

- **阶段一（进行中）**：空白 Agent 框架已提取完成，9 项验证全部通过
- **流水线**：`pipeline.yaml` 的 `steps` 为空，无 Skill 注册
- **知识库**：`data/knowledge_base/` 为空，等待填充
- **测试数据**：`tempdata/patients/张三-001/` 已导入 490 个文件（21 PDF + OCR 中间文件）

## 许可证

MIT
