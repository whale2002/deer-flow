"""修复消息历史中悬空（Dangling）工具调用的中间件。

当 AIMessage 包含 tool_calls 但历史记录中没有对应的 ToolMessage（例如由于用户中断或请求取消）时，就会出现悬空工具调用。
这会导致 LLM 因消息格式不完整而报错。

此中间件拦截模型调用，通过在发出工具调用的 AIMessage 后立即插入带有错误指示符的合成 ToolMessage 来修补这些缺口，确保正确的消息顺序。

注意：使用 wrap_model_call 而不是 before_model，以确补丁插入在正确的位置（紧跟在每个悬空的 AIMessage 之后），而不是像 before_model + add_messages reducer 那样追加到消息列表的末尾。
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """在模型调用前为悬空工具调用插入占位符 ToolMessage。

    扫描消息历史，查找 tool_calls 缺少对应 ToolMessage 的 AIMessage，
    并在有问题的 AIMessage 后立即注入合成的错误响应，以便 LLM 接收格式良好的对话。
    """

    def _build_patched_messages(self, messages: list) -> list | None:
        """返回在正确位置插入补丁的新消息列表。

        对于每个具有悬空 tool_calls（没有对应 ToolMessage）的 AIMessage，
        在该 AIMessage 之后立即插入一个合成 ToolMessage。
        如果不需要补丁，则返回 None。
        """
        # 收集所有现有 ToolMessage 的 ID
        existing_tool_msg_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                existing_tool_msg_ids.add(msg.tool_call_id)

        # 检查是否需要修补
        needs_patch = False
        for msg in messages:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids:
                    needs_patch = True
                    break
            if needs_patch:
                break

        if not needs_patch:
            return None

        # 构建新列表，在每个悬空 AIMessage 后插入补丁
        patched: list = []
        patched_ids: set[str] = set()
        patch_count = 0
        for msg in messages:
            patched.append(msg)
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids and tc_id not in patched_ids:
                    patched.append(
                        ToolMessage(
                            content="[Tool call was interrupted and did not return a result.]",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    patched_ids.add(tc_id)
                    patch_count += 1

        logger.warning(f"Injecting {patch_count} placeholder ToolMessage(s) for dangling tool calls")
        return patched

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
