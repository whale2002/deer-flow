import os
import re
from pathlib import Path

# Agent 在沙箱内部看到的虚拟路径前缀
VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


class Paths:
    """
    DeerFlow 应用程序数据的集中式路径配置。

    目录布局（主机侧）：
        {base_dir}/
        ├── memory.json
        ├── USER.md          <-- 全局用户配置文件（注入到所有 Agent）
        ├── agents/
        │   └── {agent_name}/
        │       ├── config.yaml
        │       ├── SOUL.md  <-- Agent 个性/身份（与 Lead 提示词一起注入）
        │       └── memory.json
        └── threads/
            └── {thread_id}/
                └── user-data/         <-- 在沙箱内挂载为 /mnt/user-data/
                    ├── workspace/     <-- /mnt/user-data/workspace/
                    ├── uploads/       <-- /mnt/user-data/uploads/
                    └── outputs/       <-- /mnt/user-data/outputs/

    BaseDir 解析（按优先级）：
        1. 构造函数参数 `base_dir`
        2. DEER_FLOW_HOME 环境变量
        3. 本地开发回退：cwd/.deer-flow（当 cwd 是 backend/ 目录时）
        4. 默认：$HOME/.deer-flow
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def base_dir(self) -> Path:
        """所有应用程序数据的根目录。"""
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        cwd = Path.cwd()
        if cwd.name == "backend" or (cwd / "pyproject.toml").exists():
            return cwd / ".deer-flow"

        return Path.home() / ".deer-flow"

    @property
    def memory_file(self) -> Path:
        """持久化记忆文件的路径：`{base_dir}/memory.json`。"""
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        """全局用户配置文件路径：`{base_dir}/USER.md`。"""
        return self.base_dir / "USER.md"

    @property
    def agents_dir(self) -> Path:
        """所有自定义 Agent 的根目录：`{base_dir}/agents/`。"""
        return self.base_dir / "agents"

    def agent_dir(self, name: str) -> Path:
        """特定 Agent 的目录：`{base_dir}/agents/{name}/`。"""
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        """每个 Agent 的记忆文件：`{base_dir}/agents/{name}/memory.json`。"""
        return self.agent_dir(name) / "memory.json"

    def thread_dir(self, thread_id: str) -> Path:
        """
        线程数据的主机路径：`{base_dir}/threads/{thread_id}/`

        此目录包含一个 `user-data/` 子目录，该子目录在沙箱内挂载为 `/mnt/user-data/`。

        Raises:
            ValueError: 如果 `thread_id` 包含可能导致目录遍历的不安全字符（路径分隔符或 `..`）。
        """
        if not _SAFE_THREAD_ID_RE.match(thread_id):
            raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
        return self.base_dir / "threads" / thread_id

    def sandbox_work_dir(self, thread_id: str) -> Path:
        """
        Agent 工作空间目录的主机路径。
        主机：`{base_dir}/threads/{thread_id}/user-data/workspace/`
        沙箱：`/mnt/user-data/workspace/`
        """
        return self.thread_dir(thread_id) / "user-data" / "workspace"

    def sandbox_uploads_dir(self, thread_id: str) -> Path:
        """
        用户上传文件的主机路径。
        主机：`{base_dir}/threads/{thread_id}/user-data/uploads/`
        沙箱：`/mnt/user-data/uploads/`
        """
        return self.thread_dir(thread_id) / "user-data" / "uploads"

    def sandbox_outputs_dir(self, thread_id: str) -> Path:
        """
        Agent 生成产物的主机路径。
        主机：`{base_dir}/threads/{thread_id}/user-data/outputs/`
        沙箱：`/mnt/user-data/outputs/`
        """
        return self.thread_dir(thread_id) / "user-data" / "outputs"

    def sandbox_user_data_dir(self, thread_id: str) -> Path:
        """
        用户数据根目录的主机路径。
        主机：`{base_dir}/threads/{thread_id}/user-data/`
        沙箱：`/mnt/user-data/`
        """
        return self.thread_dir(thread_id) / "user-data"

    def ensure_thread_dirs(self, thread_id: str) -> None:
        """为线程创建所有标准沙箱目录。"""
        self.sandbox_work_dir(thread_id).mkdir(parents=True, exist_ok=True)
        self.sandbox_uploads_dir(thread_id).mkdir(parents=True, exist_ok=True)
        self.sandbox_outputs_dir(thread_id).mkdir(parents=True, exist_ok=True)

    def resolve_virtual_path(self, thread_id: str, virtual_path: str) -> Path:
        """将沙箱虚拟路径解析为实际的主机文件系统路径。

        Args:
            thread_id: 线程 ID。
            virtual_path: 沙箱内看到的虚拟路径，例如
                          ``/mnt/user-data/outputs/report.pdf``。
                          匹配前会去除前导斜杠。

        Returns:
            解析后的绝对主机文件系统路径。

        Raises:
            ValueError: 如果路径不是以预期的虚拟前缀开头或检测到路径遍历尝试。
        """
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

        # 要求精确的段边界匹配以避免前缀混淆
        # (例如拒绝像 "mnt/user-dataX/..." 这样的路径)。
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.sandbox_user_data_dir(thread_id).resolve()
        actual = (base / relative).resolve()

        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected")

        return actual


# ── Singleton ────────────────────────────────────────────────────────────

_paths: Paths | None = None


def get_paths() -> Paths:
    """返回全局 Paths 单例（懒加载）。"""
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    """将 *path* 解析为绝对 ``Path``。

    相对路径相对于应用程序基目录解析。
    绝对路径按原样返回（标准化后）。
    """
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()
