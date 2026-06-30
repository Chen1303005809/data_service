# ---- 构建阶段 ----
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装构建依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- 运行阶段 ----
FROM python:3.12-slim

WORKDIR /app

# 复制已安装的包
COPY --from=builder /root/.local /root/.local

# 确保 PATH 包含 user site-packages
ENV PATH=/root/.local/bin:$PATH

# 复制应用代码
COPY . .

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/docs', timeout=5).raise_for_status()" || exit 1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
