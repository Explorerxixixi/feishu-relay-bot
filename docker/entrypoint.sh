#!/bin/bash
# Docker entrypoint —— 简化层，目前 ENTRYPOINT 直接是 cli，不需要这个，
# 留在这里以备未来需要 init 脚本（DB migration 等）时用。
set -e
exec feishu-relay-bot "$@"
