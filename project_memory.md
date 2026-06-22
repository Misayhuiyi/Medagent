# MedAgent 项目记忆

> 最后更新：2026-06-22

## 项目概述

MedAgent 三阶段重构升级项目：将现有 MedAgent 拆分为三个阶段完成重构升级 — 先提取空白 Agent 框架并保留前端，再接入新版「肺癌医生Agent」双层级流程和 folder-rag 知识库进行测试，最终全面重构项目并升级 RAG 为 SAG 架构。

## 当前阶段

**阶段二（肺癌医生流程集成）**：✅ 完成（6/6 Steps，验收 9/9 PASS），多次 Hotfix 修复集成问题，进入阶段三准备。

进度：6/6 Steps 完成 + 6 轮 Hotfix

| Step | 内容 | 状态 |
|------|------|------|
| Step 0 | 清理 10 行残留硬编码 | ✅ |
| Step 1 | 增强 AgentManager | ✅ |
| Step 2 | 改造 skill_executor | ✅ |
| Step 3 | 拷贝 Skills | ✅ |
| Step 4 | 部署支撑模块 | ✅ |
| Step 5 | 张三全流程集成测试 | ✅ |
| Step 6 | 李四/王五测试 + 验收 | ✅ |

**Hotfix 记录**：
| Hotfix | 内容 | 状态 |
|--------|------|------|
| hotfix-1 | LLM 超时修复（60s→180s） | ✅ |
| hotfix-2 | 前端标签页映射 + 报告内容修复 | ✅ |
| hotfix-3 | 文件预算增加（60KB→300KB） | ✅ |
| hotfix-4 | 对话模式多文件注入 + 模型行为修正 | ✅ |
| hotfix-5 | PDF 乱码修复 + 标签页 Markdown 回退 + 速度优化 | ✅ |
| hotfix-6 | LLM 调用失败分析（recursion_limit 15→20 + text_cleaner 超时） | ✅ |

## 项目结构

```
ai医生完整/
├── MedAgentNEW/          # 当前工作项目 — 阶段二完成
├── 老医生agent/           # 旧版 MedAgent（原始代码）
├── 更新/                 # 阶段二已接入的肺癌医生Agent全新流程
│   ├── 肺癌医生Agent/     # 10 应用层 Skill + 5 强化层 Skill（已拷贝）
│   ├── folder-rag/       # 预构建知识库（ChromaDB，已拷贝）
│   └── pdf-ocr/          # PDF OCR 预处理工具（已拷贝）
├── 任务需求与执行规划.md   # 三阶段官方规划文档
├── 阶段二详细方案.md       # 阶段二执行蓝图
└── project_memory.md     # 本文件
```

## MedAgentNEW 关键目录

```
MedAgentNEW/
├── Code/
│   ├── main.py                     # 唯一主入口（web/cli/blank 三模式）
│   └── DataCode/                   # 22 个核心模块（含 pdf_ocr.py）
├── data/
│   ├── platform.yaml               # 平台配置（含 evidence_mapping）
│   ├── skills/
│   │   ├── pipeline.yaml           # 10 步肺癌医生流水线配置
│   │   ├── 01-data-organization/   # ─┐
│   │   ├── 02-data-preprocessing/  #  │
│   │   ├── 03-loop-count-determination/ # │
│   │   ├── 04-scenario-judgment/   #  │ 10 应用层主 Skill
│   │   ├── 05-patient-history-summary/ # │ (含 33 子 Skill)
│   │   ├── 06-patient-profile/     #  │
│   │   ├── 07-treatment-plan/      #  │
│   │   ├── 08-efficacy-prediction/ #  │
│   │   ├── 09-other-suggestions/   #  │
│   │   ├── 10-report-generation/   # ─┘
│   │   ├── _shared/knowledge-retrieval/ # 共享知识检索 Skill
│   │   ├── rl-01-optimization-experience/  # ─┐
│   │   ├── rl-02-doctor-llm-finetuning/     #  │
│   │   ├── rl-03-clinical-experience/       #  │ 5 强化层主 Skill
│   │   ├── rl-04-doctor-team-llm-finetuning/ #  │ (含 10 子 Skill)
│   │   └── rl-05-model-training-automation/ # ─┘
│   ├── agents/                     # Agent 提示词配置
│   └── knowledge_base/
│       ├── tool.py                 # ChromaDB 语义搜索模块
│       └── chroma_db/              # ChromaDB 知识库（324 MB，121 PDF，29013 块）
├── frontend/                       # React 19 + TypeScript + Ant Design 6 前端
├── TempData/params.txt             # 运行参数
└── Result/                         # 输出结果目录（含 logs/）
```

## 核心架构

- **后端框架**：FastAPI（端口 8000）
- **Agent 框架**：LangGraph ReAct（`deep_agent.py` 工厂）
- **LLM 网关**：LiteLLM + AsyncOpenAI
- **前端**：React 19 + TypeScript + Ant Design 6 + Zustand 5 + ECharts 6 + Vite 8
- **Skill 管理**：SKILL.md YAML frontmatter + `pipeline.yaml` 注册
- **多 Agent 调度**：`AgentManager` 支持主 Agent + 子 Agent + Skill 临时 Agent + 隔离子 Agent
- **Skill 执行**：`skill_executor.py` 通过 `AgentManager.run_skill()` 执行 Skill（LangGraph Agent 生命周期）
- **知识检索**：当前 ChromaDB RAG → 阶段三升级为 SAG
- **RAG 工具**：`rag_query` 工具注册在 ToolRegistry，Agent 可调用检索知识库
- **报告生成**：`report_generator.py` 支持 MD/HTML/PDF 三格式，PDF 使用 fpdf2+SimHei 中文渲染

## 运行状态

| 组件 | 状态 | 地址 |
|------|------|------|
| 后端 FastAPI | 运行中 | http://localhost:8000 |
| 前端 Vite | 运行中 | http://localhost:3000 |
| 空白验证 | 9/9 PASS | `python Code/main.py blank` |
| SkillParser | 15 主 Skill | 10 应用层 + 5 强化层（强化层未接入 Pipeline） |
| 知识库 | ChromaDB 就绪 | 324 MB，121 PDF 索引 |
| 测试数据 | 3 患者 | 张三-001 (21 PDF)、李四-002、王五-003 |

## 关键超时/预算参数

| 参数 | 值 | 文件 |
|------|-----|------|
| LLM_CHAT_TIMEOUT_SECONDS | 30 | skill_executor.py |
| LLM_CHAT_STREAM_IDLE_TIMEOUT | 45 | skill_executor.py |
| LLM_TAB_TIMEOUT_SECONDS | 180 | skill_executor.py |
| SKILL_FILES_CHAR_BUDGET | 300000 | skill_executor.py |
| SKILL_PER_FILE_CHAR_BUDGET | 20000 | skill_executor.py |
| SKILL_RECURSION_LIMIT | 20 | skill_executor.py |
| CLEAN_TIMEOUT_SECONDS | 60 | text_cleaner.py |
| MAX_CHUNK_CHARS | 1200 | text_cleaner.py |
| MAX_CONCURRENT | 3 | text_cleaner.py |
| agent_manager ainvoke timeout | 165 | agent_manager.py |

## Git 仓库

- **远程地址**：https://github.com/Misayhuiyi/MedAgent.git
- **镜像仓库**：https://github.com/Misayhuiyi/Template-MedAgent.git
- **当前分支**：master
- **工作目录**：`MedAgentNEW/`
- **操作流程**：推送 MedAgent → 临切 Template-MedAgent 强制覆盖 → 切回 MedAgent

## 关键技术决策

1. **参数格式**：从制表符分隔改为两行格式（第一行参数名，第二行参数值），对齐佰茵云规范
2. **路径白名单**：`memory_store.py` 使用 `Data/memory`、`TempData/memory` 前缀（兼容小写旧路径）
3. **模块级初始化**：`web_server.py` 的 `app = create_app()` 改为 `if __name__ == "__main__"` 保护，避免 import 时执行
4. **多 Agent 能力**：完整保留 `AgentManager`，新增 `spawn_sub_agent_isolated()` + `resolve_sub_skill_path()`
5. **Skill 注入机制**：通过 `pipeline.yaml` 注册，支持 Pipeline 串行执行
6. **Skill 执行路径**：`_run_skill_via_agent()` 委托 `AgentManager.run_skill()` + LangGraph ReAct Agent
7. **RAG 查询**：Skill 中 `exec('rag_query.py')` → Agent 自动调用 `rag_query` 工具 → 内部委托 `KnowledgeBase.query()`
8. **强化层 Skills**：加 `rl-` 前缀避免与应用层编号冲突，未接入 Pipeline（阶段三规划）
9. **递归上限控制**：ReAct Agent `recursion_limit=20`（默认 25），减少无效循环 ~20%
10. **Tab 名称映射**：`_STEP_TO_TAB` dict 将 Pipeline step name 映射到前端 TabName
11. **文件注入机制**：`_format_files_for_prompt` 预算控制（总数 300K/每文件 20K），注入到系统提示词
12. **对话模式文件预览**：`_build_chat_prompt` 使用 `_format_files_for_prompt(total_budget=15000, per_file_budget=800)`，文件内容注入 user 消息
13. **Tab 渲染回退**：`renderTabContent` 优先结构化渲染，无结构化数据时回退 Markdown 渲染

## 阶段二已变更文件

| 文件 | 变更 | 说明 |
|------|------|------|
| `Code/DataCode/skill_executor.py` | 修改 | 多轮 Hotfix：超时/预算/递归上限/tab映射/文件注入/Markdown回退 |
| `Code/DataCode/agent_manager.py` | 修改 | `run_skill()` 支持 recursion_limit；文件注入系统提示词 |
| `Code/DataCode/knowledge_base.py` | 修改 | `_map_evidence()` 改为 platform.yaml 配置驱动 |
| `Code/DataCode/text_cleaner.py` | 修改 | 超时 30s→60s |
| `Code/DataCode/report_generator.py` | 修改 | fpdf2 替代 latin-1 PDF；Tab 名称更新 |
| `Code/DataCode/builtin_tools.py` | 新增工具 | `create_rag_query_tool()` |
| `Code/DataCode/web_server.py` | 新增注册 | `rag_query` 工具注册 |
| `Code/DataCode/web_routes/chat.py` | 修改 | `_load_patient_files` 文件过滤；`_build_chat_prompt` 多文件注入 |
| `Code/DataCode/web_routes/patients.py` | 修改 | 注释去张三引用 |
| `Code/DataCode/pdf_ocr.py` | 新增 | PDF OCR 模块（pypdfium2 + easyocr） |
| `data/platform.yaml` | 修改 | 新增 evidence_mapping（21 条目） |
| `data/skills/pipeline.yaml` | 修改 | 空 → 10 步肺癌医生流水线 |
| `data/skills/*/` | 新增 | 15 主 Skill + 43 子 Skill + _shared |
| `data/knowledge_base/chroma_db/` | 新增 | 324 MB ChromaDB 知识库 |
| `data/knowledge_base/tool.py` | 新增 | SentenceTransformer 语义搜索 |
| `frontend/src/components/ChatPanel/index.tsx` | 修改 | 新增快速操作按钮（文件分析/生成报告） |
| `frontend/src/components/ReportPanel/index.tsx` | 修改 | `renderTabContent` Markdown 回退 |
| `frontend/src/hooks/useChat.ts` | 修改 | tab_ready 自动切换 + tab_content 事件 |
| `frontend/src/store/reportStore.ts` | 修改 | 新增 tabContents + appendTabContent |
| `frontend/src/types/index.ts` | 修改 | 新增 TabContentData 类型 |
| `frontend/src/aidoc.css` | 修改 | 快速操作按钮样式 |

## 待完成项

- [ ] 阶段三：全面重构 + RAG→SAG 升级
- [ ] 强化层 RL Skills 接入 Pipeline
