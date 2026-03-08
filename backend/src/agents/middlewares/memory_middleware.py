"""记忆机制的中间件。"""

import re
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.memory.queue import get_memory_queue
from src.config.memory_config import get_memory_config


class MemoryMiddlewareState(AgentState):
    """与 `ThreadState` Schema 兼容的状态。"""

    pass


def _filter_messages_for_memory(messages: list[Any]) -> list[Any]:
    """过滤消息，只保留用户输入和最终的助手响应。

    过滤掉：
    - 工具消息（中间工具调用结果）
    - 带有 tool_calls 的 AI 消息（中间步骤，非最终响应）
    - UploadsMiddleware 注入到人类消息中的 <uploaded_files> 块
      （文件路径是会话范围的，不应持久化到长期记忆中）。
      用户的实际问题会被保留；只有当内容完全是上传块（去除后不剩任何内容）时，
      才会连同其配对的助手响应一起丢弃。

    只保留：
    - 人类消息（已移除临时的上传块）
    - 没有 tool_calls 的 AI 消息（最终助手响应），除非配对的人类轮次
      仅包含上传信息而没有实际用户文本。

    Args:
        messages: 所有对话消息列表。

    Returns:
        包含仅用户输入和最终助手响应的过滤列表。
    """
    _UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)

    filtered = []
    skip_next_ai = False
    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "human":
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            content_str = str(content)
            if "<uploaded_files>" in content_str:
                # 去除临时的上传块；保留用户的实际问题。
                stripped = _UPLOAD_BLOCK_RE.sub("", content_str).strip()
                if not stripped:
                    # 不剩任何内容 — 整个轮次都是上传簿记信息；
                    # 跳过它及其配对的助手响应。
                    skip_next_ai = True
                    continue
                # 用清理后的内容重建消息，以便用户的实际问题
                # 仍可用于记忆总结。
                from copy import copy

                clean_msg = copy(msg)
                clean_msg.content = stripped
                filtered.append(clean_msg)
                skip_next_ai = False
            else:
                filtered.append(msg)
                skip_next_ai = False
        elif msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                if skip_next_ai:
                    skip_next_ai = False
                    continue
                filtered.append(msg)
        # 跳过工具消息和带有 tool_calls 的 AI 消息

    return filtered


class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    """在 Agent 执行后将对话排队等待记忆更新的中间件。

    此中间件：
    1. 在每次 Agent 执行后，将对话排队等待记忆更新
    2. 仅包含用户输入和最终助手响应（忽略工具调用）
    3. 队列使用防抖（Debouncing）将多个更新批量处理
    4. 通过 LLM 总结异步更新记忆
    """

    state_schema = MemoryMiddlewareState

    def __init__(self, agent_name: str | None = None):
        """初始化 MemoryMiddleware。

        Args:
            agent_name: 如果提供，则按 Agent 存储记忆。如果为 None，则使用全局记忆。
        """
        super().__init__()
        self._agent_name = agent_name

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Agent 完成后将对话排队等待记忆更新。

        Args:
            state: 当前 Agent 状态。
            runtime: 运行时上下文。

        Returns:
            None（此中间件不需要更改状态）。
        """
        config = get_memory_config()
        if not config.enabled:
            return None

        # 从运行时上下文获取线程 ID
        thread_id = runtime.context.get("thread_id")
        if not thread_id:
            print("MemoryMiddleware: No thread_id in context, skipping memory update")
            return None

        # 从状态获取消息
        messages = state.get("messages", [])
        if not messages:
            print("MemoryMiddleware: No messages in state, skipping memory update")
            return None

        # 过滤以仅保留用户输入和最终助手响应
        filtered_messages = _filter_messages_for_memory(messages)

        # 仅当有有意义的对话时才排队
        # 至少需要一条用户消息和一条助手响应
        user_messages = [m for m in filtered_messages if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered_messages if getattr(m, "type", None) == "ai"]

        if not user_messages or not assistant_messages:
            return None

        # 将过滤后的对话排队等待记忆更新
        queue = get_memory_queue()
        queue.add(thread_id=thread_id, messages=filtered_messages, agent_name=self._agent_name)

        return None
