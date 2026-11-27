# 记账助手 · 运行镜像
# 说明：镜像里不放 .env。运行时用 --env-file 或 -e 传入 ZHIPU_API_KEY。
FROM python:3.13-slim

# 只为访问智谱 HTTPS 接口准备根证书；其余系统依赖一概不装，镜像约 300MB
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖、再拷代码：改业务代码时这一层能命中缓存，不用重装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 非 root 运行；上传目录需要可写
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/assets/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

ENV PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# 容器自检：健康检查通过才认为"镜像能起"
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

# 必须监听 0.0.0.0，否则容器外访问不到
CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501"]
