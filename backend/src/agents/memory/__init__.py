"""DeerFlow 的记忆模块。

此模块提供全局记忆机制：
- 将用户上下文和对话历史存储在 memory.json 中
- 使用 LLM 对对话进行总结并提取事实
- 将相关记忆注入系统 Prompt 以实现个性化响应
"""

from src.agents.memory.prompt import (
    FACT_EXTRACTION_PROMPT,
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
    format_memory_for_injection,
)
from src.agents.memory.queue import (
    ConversationContext,
    MemoryUpdateQueue,
    get_memory_queue,
    reset_memory_queue,
)
from src.agents.memory.updater import (
    MemoryUpdater,
    get_memory_data,
    reload_memory_data,
    update_memory_from_conversation,
)

__all__ = [
    # Prompt 工具
    "MEMORY_UPDATE_PROMPT",
    "FACT_EXTRACTION_PROMPT",
    "format_memory_for_injection",
    "format_conversation_for_update",
    # 队列（Queue）
    "ConversationContext",
    "MemoryUpdateQueue",
    "get_memory_queue",
    "reset_memory_queue",
    # 更新器（Updater）
    "MemoryUpdater",
    "get_memory_data",
    "reload_memory_data",
    "update_memory_from_conversation",
]
