# MedAgent 项目记忆

> 最后更新：2026-06-18

## 项目概述

MedAgent 三阶段重构升级项目：将现有 MedAgent 拆分为三个阶段完成重构升级 — 先提取空白 Agent 框架并保留前端，再接入新版「肺癌医生Agent」双层级流程和 folder-rag 知识库进行测试，最终全面重构项目并升级 RAG 为 SAG 架构。

## 当前阶段

**阶段一（空白 Agent 抽取）**：6/7 通过验收，剩余 10 行医疗硬编码待清理。

## 项目结构

```
ai医生完整/
├── MedAgentNEW/          # 阶段一产物 — 空白 Agent 框架（当前工作项目）
├── 老医生agent/           # 旧版 MedAgent（原始代码，已被提取）
├── 更新/                 # 阶段二待接入的肺癌医生Agent全新流程
│   ├── 肺癌医生Agent/     # 10 应用层 Skill + 5 强化层 Skill
│   ├── folder-rag/       # 预构建知识库（ChromaDB，121PDF，29013块）
│   └── pdf-ocr/          # PDF OCR 预处理工具
├── 任务需求与执行规划.md   # 三阶段官方规划文档
└── project_memory.md     # 本文件
```

## MedAgentNEW 关键目录

```
MedAgentNEW/
├── Code/
│   ├── main.py                     # 唯一主入口（web/cli/blank 三模式）
│   └── DataCode/                   # 19 个核心模块
├── data/
│   ├── platform.yaml               # 平台配置
│   ├── skills/pipeline.yaml        # Skill 流水线配置（当前为空）
│   ├── agents/                     # Agent 提示词配置
│   └── knowledge_base/             # 知识库目录（已创建，空）
├── frontend/                       # React 19 + TypeScript + Ant Design 6 前端
├── tempdata/params.txt             # 运行参数（两行格式）
└── Result/                         # 输出结果目录（已创建，空）
```

## 核心架构

- **后端框架**：FastAPI（端口 8000）
- **Agent 框架**：LangGraph ReAct（`deep_agent.py` 工厂）
- **LLM 网关**：LiteLLM
- **前端**：React 19 + TypeScript + Ant Design 6 + Zustand 5 + ECharts 6 + Vite 8
- **Skill 管理**：SKILL.md YAML frontmatter + `pipeline.yaml` 注册
- **多 Agent 调度**：`AgentManager` 支持主 Agent + 子 Agent + Skill 临时 Agent
- **知识检索**：当前 ChromaDB RAG → 阶段三升级为 SAG

## 运行状态

| 组件 | 状态 | 地址 |
|------|------|------|
| 后端 FastAPI | 运行中 | http://localhost:8000 |
| 前端 Vite | 运行中 | http://localhost:3000 |
| 空白验证 | 9/9 PASS | `python Code/main.py blank` |
| 张三测试数据 | 已导入 | TempData/patients/张三-001/ (21 PDF) |

## Git 仓库

- **远程地址**：https://github.com/Misayhuiyi/MedAgent.git
- **当前分支**：master
- **工作目录**：`MedAgentNEW/`

## 关键技术决策

1. **参数格式**：从制表符分隔改为两行格式（第一行参数名，第二行参数值），对齐佰茵云规范
2. **路径白名单**：`memory_store.py` 使用 `Data/memory`、`TempData/memory` 前缀（兼容小写旧路径）
3. **模块级初始化**：`web_server.py` 的 `app = create_app()` 改为 `if __name__ == "__main__"` 保护，避免 import 时执行
4. **多 Agent 能力**：完整保留 `AgentManager`、`schedule_sub_agents()`、`route_message()`
5. **Skill 注入机制**：新框架通过 `pipeline.yaml` 注册，支持 Pipeline 串行（旧项目 CSV 并行单 Skill）

## 待完成项

- [ ] 清理 10 行医疗硬编码（4 个文件）
  - `skill_executor.py`: Line 6 注释 + Line 102-110 硬编码分类字典
  - `knowledge_base.py`: Line 109-117 证据等级映射
  - `text_cleaner.py`: Line 22 注释
  - `web_routes/patients.py`: Line 182 注释
- [ ] 清理 `.env` 遗留变量（`NAS_PATH`、`CONFIG_PATH`）
- [ ] 阶段二：接入肺癌医生Agent 双层级流程

## 下一步

进入阶段二：将「更新」文件夹中肺癌医生Agent的 10 应用层 Skill + 5 强化层 Skill + folder-rag 知识库接入 MedAgentNEW 并测试。
