# MedAgent 项目记忆

> 最后更新：2026-07-06（前端报告显示、知识库链路、连续报告生成、V4 PDF 导出修复后）

## 项目概述

MedAgent 三阶段重构升级项目：将现有 MedAgent 拆分为三个阶段完成重构升级 — 先提取空白 Agent 框架并保留前端，再接入新版「肺癌医生Agent」双层级流程和 folder-rag 知识库进行测试，最终全面重构项目并升级 RAG 为 SAG 架构。

## 当前阶段

**阶段二（肺癌医生流程集成）**：✅ 功能集成完成，进入稳定性与性能修复阶段。

当前重点已经从“接入 10 步 Pipeline”转为：

- 前端 5 个报告页签稳定展示，不显示 LLM 中间 JSON/执行话术。
- 报告下载 PDF 对齐 V4 门诊模板，优先走 Edge HTML/CSS 高保真打印。
- 新知识库链路可加载、检索、追溯，并注入报告生成。
- 支持跨时间段连续报告生成：当前时间段可读取并注入上一时间段报告上下文。
- 生成速度优化：减少知识库注入量，默认关闭报告生成期间的后台 LLM 清洗竞争。

进度：6/6 Steps 完成 + V3.5 稳定性修复，**大模型完整流水线仍需按真实病例做长耗时回归计时**。

| Step | 内容 | 状态 |
|------|------|------|
| Step 0 | 清理 10 行残留硬编码 | ✅ |
| Step 1 | 增强 AgentManager | ✅ |
| Step 2 | 改造 skill_executor | ✅ |
| Step 3 | 拷贝 Skills | ✅ |
| Step 4 | 部署支撑模块 | ✅ |
| Step 5 | 张三全流程集成测试 | 🔄 修复中 |
| Step 6 | 李四/王五测试 + 验收 | ⏳ 待验证 |

**Hotfix 记录**：
| # | 内容 | 日期 | 状态 |
|---|------|------|------|
| hotfix-1 | LLM 超时修复（60s→180s） | 06-22 | ✅ |
| hotfix-2 | 前端标签页映射 + 报告内容修复 | 06-22 | ✅ |
| hotfix-3 | 文件预算增加（60KB→300KB） | 06-22 | ✅ |
| hotfix-4 | 对话模式多文件注入 + 模型行为修正 | 06-22 | ✅ |
| hotfix-5 | PDF 乱码 + Tab Markdown 回退 + 速度优化 | 06-22 | ✅ |
| hotfix-6 | LLM 调用失败分析（recursion 15→20） | 06-22 | ✅ |
| hotfix-7 | 报告数据持久化（report.json 写盘） | 06-23 | ✅ |
| hotfix-8 | 递归上限 + PDF 下载修复（20→24） | 06-23 | ✅ |
| hotfix-9 | 标签页内容缺失（_clean_tab_data） | 06-23 | ✅ |
| hotfix-10 | 前端智能检测替换后端清洗 | 06-23 | ✅ |
| hotfix-11 | sessions_spawn + 异步工具 + 前端中文键名 | 06-23 | ✅ |
| hotfix-12 | **Pipeline 步骤 06-10 超时断裂修复** | 06-23 | ✅（待验证） |
| hotfix-13 | PDF 报告标题/文件名格式化 | 06-23 | ✅ |
| hotfix-14 | **LLM 客户端缓存复用** | 06-23 | ✅ |
| V3.0 | 跨时间段连续报告生成 | 07-06 | ✅ |
| V3.2 | 新知识库链路对齐 + 默认快速检索 | 07-06 | ✅ |
| V3.4 | 前端报告显示稳定性 + 报告生成性能优化 | 07-06 | ✅ |
| V3.5 | 本机 Edge PDF 高保真导出权限修复 | 07-06 | ✅ |

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
│   └── DataCode/                   # 后端核心模块（含 report_context/reporting/pdf_ocr）
├── Data/
│   ├── platform.yaml               # 平台配置（含 llm/evidence_mapping）
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
│       ├── kb_manager.py           # 新知识库加载/检索/可选 reranker
│       └── chroma_db/              # ChromaDB 知识库（已索引 44307 块）
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
- **知识检索**：ChromaDB RAG，默认快速向量召回；`KB_ENABLE_RERANKER=1` 时启用本地 CrossEncoder 精排
- **RAG 工具**：`rag_query` 工具注册在 ToolRegistry，Agent 可调用检索知识库
- **报告生成**：`report_generator.py` 支持 MD/HTML/PDF；PDF 优先走 V4 HTML/CSS 模板 + Edge/Chrome 打印，失败才回退 fpdf2
- **连续报告**：`report_context.py` 归档本期报告，并在下一时间段生成时注入既往报告上下文

## 运行状态

| 组件 | 状态 | 地址 |
|------|------|------|
| 后端 FastAPI | 可运行 | http://localhost:8000 |
| 前端 Vite | 可运行 | http://localhost:3000 |
| 空白验证 | 9/9 PASS | `python Code/main.py blank` |
| SkillParser | 15 主 Skill | 10 应用层 + 5 强化层（强化层未接入 Pipeline） |
| 知识库 | ChromaDB 就绪 | 已索引文档 365，文档块 44307 |
| 测试数据 | 多患者 | 含 刘海平-004 等报告/导出验证数据 |
| Pipeline | 10 步就绪 | 快速模式默认跳过 01-04，05-09 临床步骤串行生成，10 本地汇总 |
| 前端报告 | 已修复 | 清理结构化 JSON 噪声，旧报告接口返回前清洗 |
| PDF 导出 | 已修复 | Edge 高保真导出提权验证通过；需重启后端读取新环境变量 |

## 关键超时/预算参数

| 参数 | 值 | 文件 | 说明 |
|------|-----|------|------|
| LLM_CHAT_TIMEOUT_SECONDS | 30 | skill_executor.py | |
| LLM_CHAT_STREAM_IDLE_TIMEOUT | 45 | skill_executor.py | |
| LLM_TAB_TIMEOUT_SECONDS | **660** | skill_executor.py | hotfix-12: 180→360→660 |
| SKILL_FILES_CHAR_BUDGET | 300000 | skill_executor.py | |
| SKILL_PER_FILE_CHAR_BUDGET | 20000 | skill_executor.py | |
| SKILL_RECURSION_LIMIT | **100** | skill_executor.py | hotfix-12: 20→24→50→100 |
| CLEAN_TIMEOUT_SECONDS | 60 | text_cleaner.py | |
| MAX_CHUNK_CHARS | 1200 | text_cleaner.py | |
| MAX_CONCURRENT | 3 | text_cleaner.py | |
| agent_manager ainvoke timeout | **600** | agent_manager.py | hotfix-12: 165→300→600 |
| _FILES_MAX_BYTES | 40000 | agent_manager.py | hotfix-12: 新增截断 |
| _FILES_PER_FILE_CHARS | 800 | agent_manager.py | hotfix-12: 新增截断 |
| _PREV_RESULTS_MAX_CHARS | 8000 | agent_manager.py | hotfix-12: 新增截断 |
| spawn_sub_agent timeout | **120** | agent_manager.py | hotfix-12: 新增保护 |
| spawn_sub_agent recursion | **25** | agent_manager.py | hotfix-12: 新增保护 |
| _llm_cache | 共享单例 | agent_manager.py | hotfix-14: 44 Agent 复用 1 个 ChatOpenAI |
| MEDAGENT_KB_TOP_K | 8 | 环境变量/skill_executor.py | 报告生成默认 KB 注入量，3-15 范围 |
| MEDAGENT_CLEAN_KB_CACHE | 默认关闭 | 环境变量/skill_executor.py | 设为 1 才在报告生成后后台清洗 KB |
| MEDAGENT_PDF_TMP_DIR | C:\medagent_tmp\edge_pdf | 用户环境变量 | Edge PDF 临时 profile 目录 |
| MEDAGENT_CHROMIUM_PATH | C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe | 用户环境变量 | 本机 Edge 路径 |

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
9. **递归上限控制**：ReAct Agent `recursion_limit=100`（覆盖步骤 06 的 10 子Agent+7 RAG 需求）
10. **上下文截断**：files_text 截断至 40KB（每文件 800 字符）、previous_results 截断至 8KB（最后 3 步摘要）
11. **错误分类增强**：`_classify_llm_error` 4 类→7 类（认证/超时/递归上限/上下文超限/频率限制/服务异常/网络故障）
12. **智能级联禁用**：`_is_step_specific_error()` — 仅 LLM 基础设施故障才级联禁用后续步骤，Agent 递归耗尽/上下文超限不连锁阻断
13. **子Agent 安全保护**：`spawn_sub_agent_isolated` 增加 `recursion_limit=25` + `asyncio.wait_for(120s)`
14. **Tab 名称映射**：`_STEP_TO_TAB` dict 将 Pipeline step name 映射到前端 TabName
15. **文件注入机制**：`_format_files_for_prompt` 预算控制（总数 300K/每文件 20K），注入到系统提示词
16. **对话模式文件预览**：`_build_chat_prompt` 使用 `_format_files_for_prompt(total_budget=15000, per_file_budget=800)`，文件内容注入 user 消息
17. **Tab 渲染回退**：`renderTabContent` 优先结构化渲染（STRUCTURED_KEYS 中英文键名匹配），无结构化数据时回退 Markdown
18. **串行工具调用**：`parallel_tool_calls=false` — 步骤 06 的 10 子步骤是严格串行医疗诊断流程，不可并行
19. **前端报告清洗**：后端接口和前端渲染双层清理 `完整结构化输出` / `合并输出JSON` / ```json，禁止程序结构化输出进入用户报告正文
20. **跨时间段连续生成**：05-09 临床步骤可接收 `prior_reports`；本期生成成功后归档 Markdown/JSON，供下一时间段读取
21. **知识库速度优先**：默认关闭 CrossEncoder 精排和报告生成期间 TextCleaner 后台竞争；需要高精度检索时显式设置 `KB_ENABLE_RERANKER=1`
22. **PDF 导出策略**：优先 Edge/Chrome HTML 打印；要求 `MEDAGENT_PDF_TMP_DIR` 指向纯英文、当前用户可写目录；失败才回退 fpdf2
23. **SSE 状态保护**：前端 `useChat` 使用 stream 序号忽略过期事件，避免连续生成/切换患者时旧事件覆盖新页面

## 阶段二已变更文件

| 文件 | 变更 | 说明 |
|------|------|------|
| `Code/DataCode/skill_executor.py` | 修改 | 多轮 Hotfix：超时/预算/递归上限/tab映射/文件注入/Markdown回退/_classify_llm_error 增强/_is_step_specific_error |
| `Code/DataCode/agent_manager.py` | 修改 | `run_skill()` 支持 recursion_limit；文件注入；`_truncate_files_text`；`previous_results` 截断；`_create_sessions_spawn_tool`；子Agent 超时保护 |
| `Code/DataCode/tool_registry.py` | 修改 | `to_langchain_tool()` 异步 handler 检测 + `coroutine` 参数 |
| `Code/DataCode/execute_tool.py` | 修改 | `as_tool()` handler 改为 async |
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
| `Code/DataCode/report_context.py` | 新增 | 跨时间段报告上下文读取/归档 |
| `Code/DataCode/reporting/` | 新增/修改 | V4 HTML/PDF 模板、归一化、Edge 渲染 |
| `Code/DataCode/web_routes/reports.py` | 修改 | 旧报告返回前清洗正文，下载走 V4 模板 |
| `Data/knowledge_base/kb_manager.py` | 新增/修改 | 新知识库加载、默认快速检索、可选 reranker |
| `frontend/src/components/ReportPanel/textFormat.ts` | 新增 | 对象/数组字段统一格式化，避免原始 JSON 展示 |

## 待完成项

- [ ] **真实病例完整流水线重新计时** — V3.4 后验证报告生成总耗时是否明显下降
- [ ] **前端浏览器控制台回归** — 启动后端/前端后检查报告页、下载入口、切换患者无 console error
- [ ] **Edge PDF 长期运行验证** — 后端重启后确认普通服务进程读取 `MEDAGENT_PDF_TMP_DIR` 并持续走 Edge 打印
- [ ] **多患者多时间段连续生成回归** — 验证上一期报告归档、读取、注入均生效
- [ ] 阶段三：全面重构 + RAG→SAG 升级
- [ ] 强化层 RL Skills 接入 Pipeline
