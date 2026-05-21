"""命令行入口。

子命令:
  run   启动 bot
  check 验证配置（不启动）
  --version
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from . import __version__
from .config import (
    BotConfig,
    Config,
    LoggingConfig,
    RuntimeConfig,
    UpstreamConfig,
    load_config,
)
from .logging_setup import setup_logging
from .manager import BotManager
from .models import DEFAULT_MODELS


def _build_inline_config(args) -> Config:
    """命令行直接给 --app-id / --app-secret / --upstream-* 时即时构造 config。"""
    return Config(
        upstream=UpstreamConfig(
            base_url=args.upstream_url,
            api_key=args.upstream_key or "",
        ),
        models=list(DEFAULT_MODELS),
        bots=[BotConfig(
            name=args.bot_name or "default",
            app_id=args.app_id,
            app_secret=args.app_secret,
        )],
        logging=LoggingConfig(level=args.log_level or "INFO"),
        runtime=RuntimeConfig(),
    )


def cmd_run(args) -> int:
    if args.app_id and args.app_secret and args.upstream_url:
        cfg = _build_inline_config(args)
    else:
        cfg = load_config(args.config)

    setup_logging(cfg.logging)
    logger = logging.getLogger("cli")
    logger.info("feishu-relay-bot v%s", __version__)
    logger.info(
        "loaded: %d bot(s), upstream=%s",
        len([b for b in cfg.bots if b.enabled]),
        cfg.upstream.base_url,
    )

    mgr = BotManager(cfg)
    mgr.run_forever()
    return 0


def cmd_check(args) -> int:
    try:
        cfg = load_config(args.config)
    except Exception as e:
        if not args.quiet:
            print(f"❌ config invalid: {e}", file=sys.stderr)
        return 2

    if not args.quiet:
        enabled = [b.name for b in cfg.bots if b.enabled]
        print(f"✅ config OK")
        print(f"   bots:     {len(enabled)} enabled — {', '.join(enabled)}")
        print(f"   upstream: {cfg.upstream.base_url}")
        print(f"   models:   {len(cfg.models)} — "
              f"{', '.join(m.public for m in cfg.models)}")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="feishu-relay-bot",
        description="Feishu Bot Tunnel — relay LLM messages via Feishu IM",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # run
    p_run = sub.add_parser("run", help="启动 bot 服务")
    p_run.add_argument("-c", "--config", help="config.yaml 路径")
    p_run.add_argument("--app-id", help="飞书 app id（单 bot 快速模式）")
    p_run.add_argument("--app-secret", help="飞书 app secret")
    p_run.add_argument("--upstream-url", help="上游 base URL")
    p_run.add_argument("--upstream-key", help="上游 API key")
    p_run.add_argument("--bot-name", help="单 bot 名称（默认 'default'）")
    p_run.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p_run.set_defaults(func=cmd_run)

    # check
    p_check = sub.add_parser("check", help="校验 config 文件")
    p_check.add_argument("-c", "--config", help="config.yaml 路径")
    p_check.add_argument("-q", "--quiet", action="store_true", help="只设 exit code")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
