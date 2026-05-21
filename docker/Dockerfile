FROM python:3.11-slim

LABEL maintainer="Zenwh"
LABEL description="Feishu Bot tunnel for LLM relay"

# 设置工作目录
WORKDIR /app

# 装系统依赖（最小化）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 拷贝 + 安装 Python 包
COPY pyproject.toml README.md ./
COPY feishu_relay_bot/ feishu_relay_bot/
COPY xpage_mock/ xpage_mock/
RUN pip install --no-cache-dir .

# 默认从这个路径读 config
ENV FEISHU_RELAY_BOT_CONFIG=/etc/feishu-relay-bot/config.yaml

# 用户隔离
RUN useradd -r -u 1000 -g users feishubot \
    && mkdir -p /etc/feishu-relay-bot /var/log/feishu-relay-bot \
    && chown -R feishubot:users /etc/feishu-relay-bot /var/log/feishu-relay-bot

USER feishubot

VOLUME ["/etc/feishu-relay-bot", "/var/log/feishu-relay-bot"]

# 启动
ENTRYPOINT ["feishu-relay-bot"]
CMD ["run"]
