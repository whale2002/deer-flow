from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.thread_state import ThreadDataState
from src.config.paths import Paths, get_paths


class ThreadDataMiddlewareState(AgentState):
    """与 `ThreadState` Schema 兼容的状态。"""

    thread_data: NotRequired[ThreadDataState | None]


class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """为每个线程执行创建线程数据目录。

    创建以下目录结构：
    - {base_dir}/threads/{thread_id}/user-data/workspace
    - {base_dir}/threads/{thread_id}/user-data/uploads
    - {base_dir}/threads/{thread_id}/user-data/outputs

    生命周期管理：
    - lazy_init=True（默认）：仅计算路径，目录按需创建
    - lazy_init=False：在 before_agent() 中急切创建（Eagerly Create）目录
    """

    state_schema = ThreadDataMiddlewareState

    def __init__(self, base_dir: str | None = None, lazy_init: bool = True):
        """初始化中间件。

        Args:
            base_dir: 线程数据的基础目录。默认为 Paths 解析。
            lazy_init: 如果为 True，推迟创建目录直到需要时。
                      如果为 False，在 before_agent() 中急切创建目录。
                      默认为 True 以获得最佳性能。
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()
        self._lazy_init = lazy_init

    def _get_thread_paths(self, thread_id: str) -> dict[str, str]:
        """获取线程数据目录的路径。

        Args:
            thread_id: 线程 ID。

        Returns:
            包含 workspace_path, uploads_path 和 outputs_path 的字典。
        """
        return {
            "workspace_path": str(self._paths.sandbox_work_dir(thread_id)),
            "uploads_path": str(self._paths.sandbox_uploads_dir(thread_id)),
            "outputs_path": str(self._paths.sandbox_outputs_dir(thread_id)),
        }

    def _create_thread_directories(self, thread_id: str) -> dict[str, str]:
        """创建线程数据目录。

        Args:
            thread_id: 线程 ID。

        Returns:
            包含已创建目录路径的字典。
        """
        self._paths.ensure_thread_dirs(thread_id)
        return self._get_thread_paths(thread_id)

    @override
    def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
        thread_id = runtime.context.get("thread_id")
        if thread_id is None:
            raise ValueError("Context 中必须包含 Thread ID")

        if self._lazy_init:
            # 懒加载：仅计算路径，不创建目录
            paths = self._get_thread_paths(thread_id)
        else:
            # 急切加载：立即创建目录
            paths = self._create_thread_directories(thread_id)
            print(f"Created thread data directories for thread {thread_id}")

        return {
            "thread_data": {
                **paths,
            }
        }
