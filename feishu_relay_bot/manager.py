"""
Bot Manager：一进程多 bot 协调。
"""
from __future__ import annotations

import logging
import signal
import time
from typing import List

from .bot import Bot
from .config import Config
from .models import ModelRegistry
from .upstream import UpstreamClient

logger = logging.getLogger("manager")


class BotManager:
    """启动 / 监控所有 bot，捕获 SIGTERM / SIGINT 优雅退出。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._registry = ModelRegistry(cfg.models)
        self._bots: List[Bot] = []
        self._stopping = False
        self._build_bots()

    def _build_bots(self) -> None:
        enabled = [b for b in self.cfg.bots if b.enabled]
        if not enabled:
            raise RuntimeError("no enabled bot in config")

        for bot_cfg in enabled:
            up_cfg = self.cfg.effective_upstream_for(bot_cfg)
            client = UpstreamClient(up_cfg, self._registry)
            self._bots.append(Bot(
                bot_cfg, client,
                worker_threads=self.cfg.runtime.worker_threads,
            ))

        logger.info(
            "configured %d bot(s): %s",
            len(self._bots),
            ", ".join(b.cfg.name for b in self._bots),
        )

    def run_forever(self) -> None:
        """启动所有 bot，主线程阻塞等信号。"""
        for bot in self._bots:
            bot.start()

        logger.info("all bots started, press Ctrl+C to stop")

        # 注册信号
        def handler(signum, frame):
            logger.info("received signal %d, exiting...", signum)
            self._stopping = True
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

        # 主线程心跳监控
        try:
            while not self._stopping:
                time.sleep(5)
                # 简单存活检查
                dead = [b.cfg.name for b in self._bots if not b.is_alive()]
                if dead:
                    logger.warning("bot(s) not alive: %s", dead)
        finally:
            logger.info("manager stopped")
