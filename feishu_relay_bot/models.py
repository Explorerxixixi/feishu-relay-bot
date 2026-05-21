"""
模型白名单 + 对外名 ↔ 上游名 + endpoint 映射。

由配置驱动（不再写死），见 ModelEntry 类。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ModelEntry(BaseModel):
    """单个模型的对外定义。"""
    public: str = Field(..., description="对外暴露的模型名（客户端用这个）")
    upstream: str = Field(..., description="上游（xpage / MP）实际接受的模型名")
    endpoint: str = Field(
        ...,
        description="上游端点类型：messages | responses | chat",
        pattern="^(messages|responses|chat)$",
    )


class ModelRegistry:
    """运行时持有的模型映射表。"""

    def __init__(self, entries: List[ModelEntry]):
        self._by_public: Dict[str, ModelEntry] = {e.public: e for e in entries}

    def get(self, public_name: str) -> Optional[ModelEntry]:
        return self._by_public.get(public_name)

    def is_supported(self, public_name: str) -> bool:
        return public_name in self._by_public

    def to_upstream(self, public_name: str) -> Optional[str]:
        entry = self._by_public.get(public_name)
        return entry.upstream if entry else None

    def endpoint_of(self, public_name: str) -> Optional[str]:
        entry = self._by_public.get(public_name)
        return entry.endpoint if entry else None

    def list_public_names(self) -> List[str]:
        return list(self._by_public.keys())


# 默认模型白名单（与 ModelProxy 仓库现状一致，作为 fallback）
DEFAULT_MODELS: List[ModelEntry] = [
    ModelEntry(public="claude-opus-4-7",   upstream="claude-opus-4-7",   endpoint="messages"),
    ModelEntry(public="claude-opus-4-6",   upstream="claude-opus-4-6",   endpoint="messages"),
    ModelEntry(public="claude-sonnet-4-6", upstream="claude-sonnet-4-6", endpoint="messages"),
    ModelEntry(public="gpt-5-5",           upstream="gpt-5.5",           endpoint="responses"),
    ModelEntry(public="gpt-5-4",           upstream="gpt-5.4",           endpoint="responses"),
    ModelEntry(public="kimi-2.6",          upstream="kimi-k2.6",         endpoint="chat"),
    ModelEntry(public="glm-5.1",           upstream="glm-5.1",           endpoint="chat"),
]
