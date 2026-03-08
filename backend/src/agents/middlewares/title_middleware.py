"""自动生成线程标题的中间件。"""

from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.title_config import get_title_config
from src.models import create_chat_model


class TitleMiddlewareState(AgentState):
    """与 `ThreadState` schema 兼容。"""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """在第一次用户消息后自动生成线程标题。"""

    state_schema = TitleMiddlewareState

    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        """检查我们是否应该为此线程生成标题。"""
        config = get_title_config()
        if not config.enabled:
            return False

        # 检查状态中是否已有标题
        if state.get("title"):
            return False

        # 检查是否是第一轮（至少有一条用户消息和一条助手响应）
        messages = state.get("messages", [])
        if len(messages) < 2:
            return False

        # 统计用户和助手消息
        user_messages = [m for m in messages if m.type == "human"]
        assistant_messages = [m for m in messages if m.type == "ai"]

        # 在第一次完整交互后生成标题
        return len(user_messages) == 1 and len(assistant_messages) >= 1

    async def _generate_title(self, state: TitleMiddlewareState) -> str:
        """基于对话生成简洁的标题。"""
        config = get_title_config()
        messages = state.get("messages", [])

        # 获取第一条用户消息和第一条助手响应
        user_msg_content = next((m.content for m in messages if m.type == "human"), "")
        assistant_msg_content = next((m.content for m in messages if m.type == "ai"), "")

        # 确保内容是字符串（LangChain 消息可能有列表内容）
        user_msg = str(user_msg_content) if user_msg_content else ""
        assistant_msg = str(assistant_msg_content) if assistant_msg_content else ""

        # 使用轻量级模型生成标题
        model = create_chat_model(thinking_enabled=False)

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        try:
            response = await model.ainvoke(prompt)
            # 确保响应内容是字符串
            title_content = str(response.content) if response.content else ""
            title = title_content.strip().strip('"').strip("'")
            # 限制最大字符数
            return title[: config.max_chars] if len(title) > config.max_chars else title
        except Exception as e:
            print(f"Failed to generate title: {e}")
            # 回退：使用用户消息的第一部分（按字符数）
            fallback_chars = min(config.max_chars, 50)  # 使用 max_chars 或 50，取较小值
            if len(user_msg) > fallback_chars:
                return user_msg[:fallback_chars].rstrip() + "..."
            return user_msg if user_msg else "New Conversation"

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """在第一次 Agent 响应后生成并设置线程标题。"""
        if self._should_generate_title(state):
            title = await self._generate_title(state)
            print(f"Generated thread title: {title}")

            # 将标题存储在状态中（如果配置了，将由 checkpointer 持久化）
            return {"title": title}

        return None
