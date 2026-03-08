import logging
import os
import threading

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
_config_lock = threading.Lock()


class TracingConfig(BaseModel):
    """LangSmith 追踪配置。"""

    enabled: bool = Field(...)
    api_key: str | None = Field(...)
    project: str = Field(...)
    endpoint: str = Field(...)

    @property
    def is_configured(self) -> bool:
        """检查追踪是否已完全配置（已启用且具有 API 密钥）。"""
        return self.enabled and bool(self.api_key)


_tracing_config: TracingConfig | None = None


def get_tracing_config() -> TracingConfig:
    """从环境变量获取当前追踪配置。
    Returns:
        包含当前设置的 TracingConfig。
    """
    global _tracing_config
    if _tracing_config is not None:
        return _tracing_config
    with _config_lock:
        if _tracing_config is not None:  # 获取锁后再次检查
            return _tracing_config
        _tracing_config = TracingConfig(
            enabled=os.environ.get("LANGSMITH_TRACING", "").lower() == "true",
            api_key=os.environ.get("LANGSMITH_API_KEY"),
            project=os.environ.get("LANGSMITH_PROJECT", "deer-flow"),
            endpoint=os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        )
        return _tracing_config


def is_tracing_enabled() -> bool:
    """检查 LangSmith 追踪是否已启用并配置。
    Returns:
        如果追踪已启用且具有 API 密钥，则返回 True。
    """
    return get_tracing_config().is_configured
