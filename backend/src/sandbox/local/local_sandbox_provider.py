"""本地沙箱提供者实现。"""

from src.sandbox.local.local_sandbox import LocalSandbox
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import SandboxProvider

_singleton: LocalSandbox | None = None


class LocalSandboxProvider(SandboxProvider):
    """本地沙箱提供者实现"""

    def __init__(self):
        """初始化本地沙箱提供者，设置路径映射。"""
        self._path_mappings = self._setup_path_mappings()

    def _setup_path_mappings(self) -> dict[str, str]:
        """设置本地沙箱的路径映射。

        将容器路径映射到实际的本地路径，包括 skills 目录。

        Returns:
            路径映射字典
        """
        mappings = {}

        # 映射 skills 容器路径到本地 skills 目录
        try:
            from src.config import get_app_config

            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            # 仅在 skills 目录存在时添加映射
            if skills_path.exists():
                mappings[container_path] = str(skills_path)
        except Exception as e:
            # 如果配置加载失败，记录日志但不失败
            print(f"警告：无法设置 skills 路径映射：{e}")

        return mappings

    def acquire(self, thread_id: str | None = None) -> str:
        """获取沙箱环境。

        Args:
            thread_id: 线程 ID（本地沙箱不使用）。

        Returns:
            沙箱 ID（始终返回 "local"）。
        """
        global _singleton
        if _singleton is None:
            _singleton = LocalSandbox("local", path_mappings=self._path_mappings)
        return _singleton.id

    def get(self, sandbox_id: str) -> Sandbox | None:
        """通过 ID 获取沙箱。

        Args:
            sandbox_id: 沙箱 ID。

        Returns:
            沙箱实例，如果不存在则返回 None。
        """
        if sandbox_id == "local":
            if _singleton is None:
                self.acquire()
            return _singleton
        return None

    def release(self, sandbox_id: str) -> None:
        """释放沙箱。

        LocalSandbox 使用单例模式，无需清理。
        注意：此方法有意不由 SandboxMiddleware 调用，
        以允许在同一线程的多次交互中复用沙箱。
        对于基于 Docker 的提供者（如 AioSandboxProvider），
        清理在应用程序关闭时通过 shutdown() 方法进行。
        """
        pass
