"""沙箱提供者抽象基类和工厂函数。"""

from abc import ABC, abstractmethod

from src.config import get_app_config
from src.reflection import resolve_class
from src.sandbox.sandbox import Sandbox


class SandboxProvider(ABC):
    """沙箱提供者的抽象基类"""

    @abstractmethod
    def acquire(self, thread_id: str | None = None) -> str:
        """获取沙箱环境并返回其 ID。

        Returns:
            获取的沙箱环境 ID。
        """
        pass

    @abstractmethod
    def get(self, sandbox_id: str) -> Sandbox | None:
        """通过 ID 获取沙箱环境。

        Args:
            sandbox_id: 要保留的沙箱环境 ID。
        """
        pass

    @abstractmethod
    def release(self, sandbox_id: str) -> None:
        """释放沙箱环境。

        Args:
            sandbox_id: 要销毁的沙箱环境 ID。
        """
        pass


_default_sandbox_provider: SandboxProvider | None = None


def get_sandbox_provider(**kwargs) -> SandboxProvider:
    """获取沙箱提供者单例。

    返回缓存的单例实例。使用 `reset_sandbox_provider()` 清除缓存，
    或使用 `shutdown_sandbox_provider()` 正确关闭并清除。

    Returns:
        沙箱提供者实例。
    """
    global _default_sandbox_provider
    if _default_sandbox_provider is None:
        config = get_app_config()
        cls = resolve_class(config.sandbox.use, SandboxProvider)
        _default_sandbox_provider = cls(**kwargs)
    return _default_sandbox_provider


def reset_sandbox_provider() -> None:
    """重置沙箱提供者单例。

    清除缓存的实例而不调用关闭。下次调用 `get_sandbox_provider()` 将创建新实例。
    用于测试或切换配置。

    注意：如果提供者有活动的沙箱，它们将成为孤立资源。
    如需正确清理，请使用 `shutdown_sandbox_provider()`。
    """
    global _default_sandbox_provider
    _default_sandbox_provider = None


def shutdown_sandbox_provider() -> None:
    """关闭并重置沙箱提供者。

    正确关闭提供者（释放所有沙箱）后再清除单例。
    在应用程序关闭或需要完全重置沙箱系统时调用此函数。
    """
    global _default_sandbox_provider
    if _default_sandbox_provider is not None:
        if hasattr(_default_sandbox_provider, "shutdown"):
            _default_sandbox_provider.shutdown()
        _default_sandbox_provider = None


def set_sandbox_provider(provider: SandboxProvider) -> None:
    """设置自定义沙箱提供者实例。

    允许注入自定义或模拟提供者以用于测试目的。

    Args:
        provider: 要使用的 SandboxProvider 实例。
    """
    global _default_sandbox_provider
    _default_sandbox_provider = provider
