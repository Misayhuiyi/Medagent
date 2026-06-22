#!/bin/bash
# Docker/start.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# 创建必要目录
mkdir -p TempData Result Data/knowledge_base Data/memory

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "警告: .env 文件不存在，从 .env.example 复制"
    cp .env.example .env
fi

# 运行（一次性执行，非长驻）
docker compose -f Docker/docker-compose.yaml --env-file .env up --build

echo "AgentTemplate 执行完成"
echo "结果目录: Result/"
