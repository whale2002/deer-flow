from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.thread_state import SandboxState, ThreadDataState
from src.sandbox import get_sandbox_provider


class SandboxMiddlewareState(AgentState):
    """与 `ThreadState` Schema 兼容的状态定义。"""

    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]


class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    """创建沙箱环境并分配给 Agent。

    生命周期管理：
    - lazy_init=True（默认）：首次工具调用时获取沙箱
    - lazy_init=False：在首次 Agent 调用时获取沙箱（在 before_agent 中）
    - 同一线程内多次交互会复用沙箱
    - 每次 Agent 调用后不会释放沙箱，避免重复创建
    - 应用关闭时通过 SandboxProvider.shutdown() 清理
    """

    state_schema = SandboxMiddlewareState

    def __init__(self, lazy_init: bool = True):
        """初始化沙箱中间件。

        Args:
            lazy_init: 如果为 True，推迟到首次工具调用时获取沙箱。
                      如果为 False，在 before_agent() 中立即获取沙箱。
                      默认为 True 以获得最佳性能。
        """
        super().__init__()
        self._lazy_init = lazy_init

    def _acquire_sandbox(self, thread_id: str) -> str:
        """获取沙箱环境。

        Args:
            thread_id: 线程 ID。

        Returns:
            沙箱 ID。
        """
        provider = get_sandbox_provider()
        sandbox_id = provider.acquire(thread_id)
        print(f"正在获取沙箱 {sandbox_id}")
        return sandbox_id

    @override
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        # 如果启用了 lazy_init，跳过获取
        if self._lazy_init:
            return super().before_agent(state, runtime)

        # 急切初始化（原有行为）
        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = runtime.context["thread_id"]
            print(f"线程 ID: {thread_id}")
            sandbox_id = self._acquire_sandbox(thread_id)
            return {"sandbox": {"sandbox_id": sandbox_id}}
        return super().before_agent(state, runtime)
