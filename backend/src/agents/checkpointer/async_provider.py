"""异步检查点工厂 (Async Checkpointer Factory)。

为需要适当资源清理的长时间运行的异步服务器提供 **异步上下文管理器**。

支持的后端：memory (内存), sqlite, postgres。

用法 (例如 FastAPI 生命周期)::

    from src.agents.checkpointer.async_provider import make_checkpointer

    async with make_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer  # 如果未配置则为 None

同步用法请参见 :mod:`src.agents.checkpointer.provider`。
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.types import Checkpointer

from src.agents.checkpointer.provider import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_INSTALL,
    SQLITE_INSTALL,
    _resolve_sqlite_conn_str,
)
from src.config.app_config import get_app_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 异步工厂 (Async factory)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_checkpointer(config) -> AsyncIterator[Checkpointer]:
    """构建和拆除检查点保存器的异步上下文管理器。"""
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        import pathlib

        conn_str = _resolve_sqlite_conn_str(config.connection_string or "store.db")
        # 仅为真实文件系统路径创建父目录
        if conn_str != ":memory:" and not conn_str.startswith("file:"):
            pathlib.Path(conn_str).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
            await saver.setup()
            yield saver
        return

    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        async with AsyncPostgresSaver.from_conn_string(config.connection_string) as saver:
            await saver.setup()
            yield saver
        return

    raise ValueError(f"未知的检查点类型: {config.type!r}")


# ---------------------------------------------------------------------------
# 公共异步上下文管理器
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def make_checkpointer() -> AsyncIterator[Checkpointer | None]:
    """生成调用者生命周期内的检查点保存器的异步上下文管理器。
    资源在进入时打开，退出时关闭 —— 无全局状态::

        async with make_checkpointer() as checkpointer:
            app.state.checkpointer = checkpointer

    当 *config.yaml* 中未配置检查点保存器时 yield ``None``。
    """

    config = get_app_config()

    if config.checkpointer is None:
        yield None
        return

    async with _async_checkpointer(config.checkpointer) as saver:
        yield saver
