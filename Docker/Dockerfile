# Docker/Dockerfile
FROM python:3.13-slim

WORKDIR /app

# 安装 Python 依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# 复制应用代码
COPY Code/ ./Code/
COPY Data/ ./Data/
COPY TempData/ ./TempData/

# 创建必要目录
RUN mkdir -p /app/Result /app/Data/memory /app/Data/knowledge_base

# 环境变量
ENV ANTHROPIC_API_KEY=""
ENV OPENAI_API_KEY=""
ENV DASHSCOPE_API_KEY=""

ENTRYPOINT ["python", "Code/main.py", "web"]
