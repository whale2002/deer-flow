"""同步检查点工厂 (Sync Checkpointer Factory)。

为 LangGraph 图编译和 CLI 工具提供 **同步单例** 和 **同步上下文管理器**。

支持的后端：memory (内存), sqlite, postgres。

用法::

    from src.agents.checkpointer.provider import get_checkpointer, checkpointer_context

    # 单例 (Singleton) — 跨调用重用，进程退出时关闭
    cp = get_checkpointer()

    # 一次性 (One-shot) — 新连接，块退出时关闭
    with checkpointer_context() as cp:
        graph.invoke(input, config={"configurable": {"thread_id": "1"}})
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator

from langgraph.types import Checkpointer

from src.config.app_config import get_app_config
from src.config.checkpointer_config import CheckpointerConfig
from src.config.paths import resolve_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 错误消息常量 — 也被 aio.provider 导入使用
# ---------------------------------------------------------------------------

SQLITE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite checkpointer. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_INSTALL = "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install it with: uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool"
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"

# ---------------------------------------------------------------------------
# 同步工厂 (Sync factory)
# ---------------------------------------------------------------------------


def _resolve_sqlite_conn_str(raw: str) -> str:
    """返回可供 ``SqliteSaver`` 使用的 SQLite 连接字符串。

    SQLite 特殊字符串 (``":memory:"`` 和 ``file:`` URIs) 保持不变。
    普通文件系统路径 — 相对或绝对 — 通过 :func:`resolve_path` 解析为绝对字符串。
    """
    if raw == ":memory:" or raw.startswith("file:"):
        return raw
    return str(resolve_path(raw))


@contextlib.contextmanager
def _sync_checkpointer_cm(config: CheckpointerConfig) -> Iterator[Checkpointer]:
    """创建和拆除同步检查点保存器的上下文管理器。

    返回配置好的 ``Checkpointer`` 实例。底层连接或池的资源清理
    由本模块中的更高级别帮助程序（如单例工厂或上下文管理器）处理；
    此函数不返回单独的清理回调。
    """
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
        yield InMemorySaver()
        return

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = _resolve_sqlite_conn_str(config.connection_string or "store.db")
        with SqliteSaver.from_conn_string(conn_str) as saver:
            saver.setup()
            logger.info("Checkpointer: using SqliteSaver (%s)", conn_str)
            yield saver
        return

    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        with PostgresSaver.from_conn_string(config.connection_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"未知的检查点类型: {config.type!r}")


# ---------------------------------------------------------------------------
# 同步单例 (Sync singleton)
# ---------------------------------------------------------------------------

_checkpointer: Checkpointer = None
_checkpointer_ctx = None  # 保持连接活跃的打开的上下文管理器


def get_checkpointer() -> Checkpointer | None:
    """返回全局同步检查点单例，在首次调用时创建。

    当 *config.yaml* 中未配置检查点保存器时返回 ``None``。

    Raises:
        ImportError: 如果未安装配置的后端所需的包。
        ValueError: 如果需要连接字符串的后端缺少 ``connection_string``。
    """
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    from src.config.checkpointer_config import get_checkpointer_config

    config = get_checkpointer_config()
    if config is None:
        return None

    _checkpointer_ctx = _sync_checkpointer_cm(config)
    _checkpointer = _checkpointer_ctx.__enter__()

    return _checkpointer


def reset_checkpointer() -> None:
    """重置同步单例，强制在下次调用时重新创建。

    关闭任何打开的后端连接并清除缓存的实例。
    在测试或配置更改后很有用。
    """
    global _checkpointer, _checkpointer_ctx
    if _checkpointer_ctx is not None:
        try:
            _checkpointer_ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during checkpointer cleanup", exc_info=True)
        _checkpointer_ctx = None
    _checkpointer = None


# ---------------------------------------------------------------------------
# 同步上下文管理器 (Sync context manager)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def checkpointer_context() -> Iterator[Checkpointer | None]:
    """Yield 检查点保存器并在退出时清理的同步上下文管理器。

    与 :func:`get_checkpointer` 不同，此函数 **不** 缓存实例 —
    每个 ``with`` 块都会创建并销毁自己的连接。在 CLI 脚本或测试中
    如果需要确定性清理，请使用此方法::

        with checkpointer_context() as cp:
            graph.invoke(input, config={"configurable": {"thread_id": "1"}})
    """

    config = get_app_config()
    if config.checkpointer is None:
        yield None
        return

    with _sync_checkpointer_cm(config.checkpointer) as saver:
        yield saver
