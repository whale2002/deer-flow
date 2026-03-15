"""限制每个模型响应中最大并发子代理工具调用数量的中间件。"""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.subagents.executor import MAX_CONCURRENT_SUBAGENTS

logger = logging.getLogger(__name__)

# max_concurrent_subagents 的有效范围
MIN_SUBAGENT_LIMIT = 2
MAX_SUBAGENT_LIMIT = 4


def _clamp_subagent_limit(value: int) -> int:
    """将子代理限制在有效范围 [2, 4] 内。"""
    return max(MIN_SUBAGENT_LIMIT, min(MAX_SUBAGENT_LIMIT, value))


class SubagentLimitMiddleware(AgentMiddleware[AgentState]):
    """截断单个模型响应中多余的 'task' 工具调用。

    当 LLM 在一个响应中生成的并行任务工具调用超过 max_concurrent 时，
    此中间件仅保留前 max_concurrent 个，并丢弃其余的。
    这比基于 Prompt 的限制更可靠。

    Args:
        max_concurrent: 允许的最大并发子代理调用数。
            默认为 MAX_CONCURRENT_SUBAGENTS (3)。限制在 [2, 4] 范围内。
    """

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_SUBAGENTS):
        super().__init__()
        self.max_concurrent = _clamp_subagent_limit(max_concurrent)

    def _truncate_task_calls(self, state: AgentState) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        name == "task" = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        # 统计任务工具调用
        task_indices = [i for i, tc in enumerate(tool_calls) if tc.get("name") == "task"]
        if len(task_indices) <= self.max_concurrent:
            return None

        # 构建要丢弃的索引集（超出限制的多余任务调用）
        indices_to_drop = set(task_indices[self.max_concurrent :])
        truncated_tool_calls = [tc for i, tc in enumerate(tool_calls) if i not in indices_to_drop]

        dropped_count = len(indices_to_drop)
        logger.warning(f"Truncated {dropped_count} excess task tool call(s) from model response (limit: {self.max_concurrent})")

        # 替换具有截断后 tool_calls 的 AIMessage（相同的 ID 会触发替换）
        updated_msg = last_msg.model_copy(update={"tool_calls": truncated_tool_calls})
        return {"messages": [updated_msg]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state)
