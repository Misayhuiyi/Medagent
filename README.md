# MedAgent — AI 肿瘤辅助决策系统

基于多轮推理和工具调用的 AI 医疗辅助诊断平台。用户上传病历文件，MedAgent 通过 6 个专项 Skill 完成病史提取、肿瘤评估、方案推荐、疗效预测和人文关怀建议，结果实时推送到 Web UI。

## 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| Agent 框架 | LangGraph (DeepAgents) | 0.2+ |
| LLM 网关 | LiteLLM Proxy | 1.0+ |
| 后端 API | FastAPI + SSE (sse-starlette) | — |
| 前端 UI | React 19 + TypeScript 6 + Ant Design 6 | — |
| 状态管理 | Zustand 5 | — |
| 图表 | ECharts 6 | — |
| 构建工具 | Vite 8 | — |
| 容器化 | Docker + docker-compose | — |
| 包管理 | uv (Python), npm (Node) | — |

## 目录结构

```
MedAgent/
├── Code/
│   ├── main.py                   # 唯一主入口（web/cli/blank 三模式）
│   └── DataCode/                 # 后端模块 (16 个)
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
│       ├── mcp_connector.py       # MCP streamable_http 连接器
│       ├── execution_logger.py    # 三格式日志（JSON/MD/TXT）
│       ├── report_generator.py    # 报告生成器
│       ├── web_server.py          # FastAPI 应用工厂
│       └── web_routes/            # API 路由
│           ├── patients.py          # 患者列表与文件读取
│           ├── chat.py              # SSE 流式对话
│           └── reports.py           # 报告 CRUD 与下载
├── data/
│   ├── platform.yaml              # 平台配置
│   ├── agents/main/               # Agent 配置（系统提示词、可用工具）
│   └── skills/                    # Skill 定义（通过 pipeline.yaml 注册）
│       └── pipeline.yaml           # 流水线步骤配置
├── tempdata/
│   ├── params.txt                 # 运行参数（两行格式）
│   └── patients/                  # 患者数据（PDF + OCR Markdown）
├── Result/                        # 分析结果输出（按 session 分目录）
├── frontend/                      # React 前端
│   └── src/
│       ├── components/            # UI 组件
│       │   ├── TopBar/              # 顶部导航栏
│       │   ├── PatientList/         # 患者卡片列表 + 文件抽屉
│       │   ├── ChatPanel/           # AI 对话面板（SSE 流式）
│       │   ├── ReportPanel/         # 5 标签页报告面板
│       │   └── common/              # 通用组件（MarkdownRenderer）
│       ├── store/                 # Zustand stores
│       │   ├── patientStore.ts      # 患者选择与文件
│       │   ├── chatStore.ts         # 聊天消息与流状态
│       │   ├── reportStore.ts       # 报告数据与标签页
│       │   └── editStore.ts         # 编辑模式与表单
│       ├── hooks/useChat.ts       # SSE 连接管理
│       ├── services/api.ts        # API 客户端 + SSE 解析
│       └── types/index.ts         # TypeScript 类型定义
├── Docker/                        # 容器化部署
└── tests/                         # 后端测试
```

## 架构概览

```
┌──────────────┐     /api proxy      ┌──────────────────┐     SSE/LiteLLM     ┌──────────┐
│              │  ──────────────────  │                  │  ─────────────────  │          │
│   Frontend   │   localhost:3000    │   FastAPI :8000  │                     │  LLM API │
│   React:3000 │  ─────────────────  │                  │  ─────────────────  │          │
│              │     Vite Proxy      │   SkillExecutor  │   LiteLLM :4000     │          │
└──────────────┘                     │   AgentManager   │                     └──────────┘
                                     │   6 × Skills     │
                                     └──────────────────┘
```

**前端** (React 19) 通过 Vite 开发代理访问后端 API。**后端** (FastAPI) 接收请求后，由 SkillExecutor 调度 6 个专项 Skill 依次执行，每个 Skill 的结果通过 SSE 实时推送到前端对应的报告标签页。

### 前端架构

三面板布局，左中右结构：

| 面板 | 组件 | 宽度 | 功能 |
|------|------|------|------|
| 左侧 | `PatientList` | 260px 固定 | 患者卡片列表、文件浏览器 |
| 中间 | `ChatPanel` | flex 自适应 | AI 对话、SSE 流式消息、Markdown 渲染 |
| 右侧 | `ReportPanel` | 460px 固定 | 5 标签页报告 + 编辑 + 导出 |

报告标签页由 SSE `tab_ready` 事件驱动逐个填充：

```
analyze-data → [用户发送消息]
  → generate_history  → SSE tab_ready(history)  → TabHistory 渲染
  → generate_overview → SSE tab_ready(overview) → TabOverview 渲染
  → generate_treatment→ SSE tab_ready(treatment)→ TabTreatment 渲染
  → generate_prediction→SSE tab_ready(prediction)→ TabPrediction 渲染
  → generate_care     → SSE tab_ready(care)     → TabCare 渲染
  → SSE done
```

### 后端架构

核心执行链：`web_routes/chat.py` → `SkillExecutor` → `AgentManager` → `DeepAgent (LangGraph)` → 工具调用 → 结果组装 → SSE 推送

```
请求入口
  └─ web_routes/chat.py          # SSE 流式响应
       └─ SkillExecutor          # 按序调度 6 个 Skill
            └─ AgentManager      # Agent 生命周期、子 Agent
                 └─ DeepAgent    # LangGraph ReAct 循环
                      ├─ ToolRegistry   # 工具查找
                      ├─ ExecuteTool    # 权限检查 + 执行
                      └─ MemoryStore    # 上下文卸载
```

## API 接口

### 患者管理

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/patients` | 获取患者列表（含文件数、诊断信息） |
| `GET` | `/api/patients/{id}/files` | 获取患者文件列表（含 `has_ocr` 标志） |
| `GET` | `/api/patients/{id}/files/{path}` | 读取文件内容（PDF 自动转发到 OCR Markdown） |

### AI 对话

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/chat/{id}/messages` | 发送消息，触发 Skill 执行链，**SSE 流式响应** |
| `GET` | `/api/chat/{id}/history` | 获取历史对话 |

**SSE 事件类型：**

| 事件 | 数据 | 说明 |
|------|------|------|
| `status` | `{ state: string }` | 状态更新（如"正在分析..."） |
| `token` | `{ content: string }` | 流式文本 token |
| `tab_ready` | `{ tab: TabName, data: {...} }` | 报告标签页数据就绪 |
| `error` | `{ tab?: TabName, message: string }` | 错误信息 |
| `done` | `{}` | 执行完成 |

### 报告管理

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/reports/{id}` | 获取报告 JSON（5 个标签页） |
| `POST` | `/api/reports/{id}` | 保存编辑后的报告 |
| `GET` | `/api/reports/{id}/download?format=md\|html\|pdf` | 下载报告 |

### 报告数据结构

```typescript
interface ReportData {
  history?: HistoryData      // 患者病史：时间线 + 肿瘤大小曲线
  overview?: OverviewData    // 患者概况：TNM 分期 + 疗效评估 + 不良反应
  treatment?: TreatmentData  // 治疗方案：多方案对比评分 + 临床试验匹配
  prediction?: PredictionData// 疗效预测：肿瘤/不良反应预测曲线 + PFS/OS
  care?: CareData            // 人文关怀：心理支持 + 中医建议 + 护理
}
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- LLM API Key（至少配置一个：Anthropic / OpenAI / DashScope / DeepSeek）

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入 API 密钥
```

```env
# .env
ANTHROPIC_API_KEY=sk-ant-xxx     # Claude 系列
OPENAI_API_KEY=sk-xxx            # GPT 系列
DASHSCOPE_API_KEY=sk-xxx         # 通义千问系列
DEEPSEEK_API_KEY=sk-xxx          # DeepSeek 系列

HOST_PORT=8000                   # FastAPI 端口
```

### 2. 启动后端

```bash
# 创建虚拟环境
uv venv .venv --python 3.11
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 安装依赖
uv pip install -e ".[dev]"
uv pip install langgraph langchain-core langchain-openai fastapi sse-starlette uvicorn apscheduler litellm

# 启动 FastAPI 服务
python -m uvicorn Code.DataCode.web_server:create_app --factory --host 0.0.0.0 --port 8000
```

后端启动在 `http://localhost:8000`。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端启动在 `http://localhost:3000`，自动代理 `/api` 请求到后端 `localhost:8000`。

### 4. CLI 模式（无前端）

```bash
python Code/main.py
```

直接执行主 Skill，结果输出到 `Result/{session_id}/`。

## 配置说明

### 平台配置 (`data/platform.yaml`)

```yaml
llm:
  base_url: "http://localhost:4000"   # LiteLLM 代理地址
  default_model: "deepseek-v4-pro"    # 默认模型
  context_length: 200000              # 上下文长度

workspace:
  root: "/workspace/user_data"

memory:
  long_term_path: "tempdata/memory/long_term"

context:
  summary_threshold: 0.7              # 触发压缩的 Token 比例
  compression_buffer_tokens: 8000
```

### LLM 模型路由 (`data/litellm_config.yaml`)

通过 LiteLLM Proxy 统一路由多模型，API Key 从环境变量读取：

| 模型名 | 提供商 | 环境变量 |
|--------|--------|----------|
| `claude-sonnet-4-6` | Anthropic | `ANTHROPIC_API_KEY` |
| `claude-opus-4-7` | Anthropic | `ANTHROPIC_API_KEY` |
| `gpt-5.4` | OpenAI | `OPENAI_API_KEY` |
| `qwen3-235b` | DashScope | `DASHSCOPE_API_KEY` |
| `deepseek-v4-pro` | DeepSeek | `DEEPSEEK_API_KEY` |

### 患者数据格式

患者数据存放在 `tempdata/patients/` 下：

```
tempdata/patients/
└── {姓名}-{ID}/
    └── {分类}/                  # 如 影像、检验、病理
        ├── {文件名}.pdf         # 原始 PDF
        └── {文件名}/ocr/
            └── {文件名}.md      # OCR 提取的 Markdown
```

## Docker 部署

```bash
cp .env.example .env
# 编辑 .env

# 一键构建并启动
bash Docker/start.sh
```

容器启动后执行 `RunAgeAtgent.py`（一次性任务模式）。

**Volume 映射：**

| 宿主机 | 容器内 | 权限 |
|--------|--------|------|
| `$NAS_PATH` | `/app/tempdata` | 只读 |
| `$RESULT_PATH` | `/app/Result` | 读写 |
| `./data` | `/app/data` | 读写 |

## 测试

```bash
# 后端测试
pytest tests/ -v --tb=short

# 前端测试
cd frontend && npx vitest run
```

## 安全设计

- **路径白名单**：Agent 只能写入 `Result/` 和 `data/memory/`
- **文件大小限制**：读写操作 10MB 上限
- **日志脱敏**：Result/ 下只有 `.txt` 脱敏日志，不暴露患者信息
- **Session ID 验证**：格式 `YYYY-MM-DD_HHMMSS_<6位hex>`，防止路径遍历
- **API Key**：支持环境变量覆盖 YAML 明文配置

## 许可证

MIT
