"""日志配置工具。"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from .config import LoggingConfig


def setup_logging(cfg: LoggingConfig) -> None:
    """根据 LoggingConfig 配置 root logger。"""
    level = getattr(logging, cfg.level.upper(), logging.INFO)

    handlers = []
    if cfg.file:
        handlers.append(logging.FileHandler(cfg.file, encoding="utf-8"))
    else:
        handlers.append(logging.StreamHandler(sys.stdout))

    if cfg.format == "json":
        # 简单 JSON 单行（不引入 python-json-logger 依赖）
        fmt = '{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    formatter = logging.Formatter(fmt)
    for h in handlers:
        h.setFormatter(formatter)

    root = logging.getLogger()
    # 清掉已有 handler 避免重复
    root.handlers = []
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)
