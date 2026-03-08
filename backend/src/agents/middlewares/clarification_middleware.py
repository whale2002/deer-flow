"""拦截澄清请求并将其呈现给用户的中间件。"""

from collections.abc import Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


class ClarificationMiddlewareState(AgentState):
    """与 `ThreadState` schema 兼容。"""

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """拦截澄清工具调用并中断执行以向用户提问。

    当模型调用 `ask_clarification` 工具时，此中间件：
    1. 在执行前拦截工具调用
    2. 提取澄清问题和元数据
    3. 格式化用户友好的消息
    4. 返回一个 Command，中断执行并呈现问题
    5. 等待用户响应后再继续

    这取代了基于工具的方法（即澄清会继续对话流）。
    """

    state_schema = ClarificationMiddlewareState

    def _is_chinese(self, text: str) -> bool:
        """检查文本是否包含中文字符。

        Args:
            text: 要检查的文本

        Returns:
            如果文本包含中文字符则返回 True
        """
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict) -> str:
        """将澄清参数格式化为用户友好的消息。

        Args:
            args: 包含澄清细节的工具调用参数

        Returns:
            格式化的消息字符串
        """
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = args.get("options", [])

        # 特定类型的图标
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        # 自然地构建消息
        message_parts = []

        # 将图标和问题放在一起，使流程更自然
        if context:
            # 如果有上下文，先将其作为背景呈现
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            # 仅显示带图标的问题
            message_parts.append(f"{icon} {question}")

        # 以更清晰的格式添加选项
        if options and len(options) > 0:
            message_parts.append("")  # 空行用于分隔
            for i, option in enumerate(options, 1):
                message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        """处理澄清请求并返回中断执行的命令。

        Args:
            request: 工具调用请求

        Returns:
            中断执行并带有格式化澄清消息的 Command
        """
        # 提取澄清参数
        args = request.tool_call.get("args", {})
        question = args.get("question", "")

        print("[ClarificationMiddleware] Intercepted clarification request")
        print(f"[ClarificationMiddleware] Question: {question}")

        # 格式化澄清消息
        formatted_message = self._format_clarification_message(args)

        # 获取工具调用 ID
        tool_call_id = request.tool_call.get("id", "")

        # 创建包含格式化问题的 ToolMessage
        # 这将被添加到消息历史记录中
        tool_message = ToolMessage(
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
        )

        # 返回一个 Command：
        # 1. 添加格式化的工具消息
        # 2. 通过跳转到 __end__ 中断执行
        # 注意：我们要在这里添加额外的 AIMessage - 前端会检测
        # 并直接显示 ask_clarification 工具消息
        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """拦截 ask_clarification 工具调用并中断执行（同步版本）。

        Args:
            request: 工具调用请求
            handler: 原始工具执行处理程序

        Returns:
            中断执行并带有格式化澄清消息的 Command
        """
        # 检查这是否是 ask_clarification 工具调用
        if request.tool_call.get("name") != "ask_clarification":
            # 不是澄清调用，正常执行
            return handler(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """拦截 ask_clarification 工具调用并中断执行（异步版本）。

        Args:
            request: 工具调用请求
            handler: 原始工具执行处理程序（异步）

        Returns:
            中断执行并带有格式化澄清消息的 Command
        """
        # 检查这是否是 ask_clarification 工具调用
        if request.tool_call.get("name") != "ask_clarification":
            # 不是澄清调用，正常执行
            return await handler(request)

        return self._handle_clarification(request)
