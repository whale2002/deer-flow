"""带防抖机制的记忆更新队列。"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.config.memory_config import get_memory_config


@dataclass
class ConversationContext:
    """待处理记忆更新的对话上下文（类似于 Redux Store 中的一次状态更新）。"""

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    agent_name: str | None = None


class MemoryUpdateQueue:
    """带防抖（Debounce）机制的记忆更新队列。

    此队列收集对话上下文，并在可配置的防抖周期后处理它们。
    在防抖窗口内接收到的多个对话会被批量处理（类似于前端输入框的防抖，避免频繁触发后端请求）。
    """

    def __init__(self):
        """初始化记忆更新队列。"""
        self._queue: list[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False

    def add(self, thread_id: str, messages: list[Any], agent_name: str | None = None) -> None:
        """将对话添加到更新队列中。

        Args:
            thread_id: 线程 ID。
            messages: 对话消息列表（Array）。
            agent_name: 如果提供，则按 Agent 存储记忆；如果为 None，则使用全局记忆。
        """
        config = get_memory_config()
        if not config.enabled:
            return

        context = ConversationContext(
            thread_id=thread_id,
            messages=messages,
            agent_name=agent_name,
        )

        with self._lock:
            # 检查此线程是否已有待处理的更新
            # 如果有，用新的更新替换它（覆盖旧状态）
            self._queue = [c for c in self._queue if c.thread_id != thread_id]
            self._queue.append(context)

            # 重置或启动防抖定时器
            self._reset_timer()

        print(f"Memory update queued for thread {thread_id}, queue size: {len(self._queue)}")

    def _reset_timer(self) -> None:
        """重置防抖定时器。"""
        config = get_memory_config()

        # 如果存在现有定时器，则取消它（clearTimeout）
        if self._timer is not None:
            self._timer.cancel()

        # 启动新定时器（setTimeout）
        self._timer = threading.Timer(
            config.debounce_seconds,
            self._process_queue,
        )
        self._timer.daemon = True
        self._timer.start()

        print(f"Memory update timer set for {config.debounce_seconds}s")

    def _process_queue(self) -> None:
        """处理所有排队的对话上下文。"""
        # 在此处导入以避免循环依赖（Circular Dependency）
        from src.agents.memory.updater import MemoryUpdater

        with self._lock:
            if self._processing:
                # 正在处理中，重新调度
                self._reset_timer()
                return

            if not self._queue:
                return

            self._processing = True
            contexts_to_process = self._queue.copy()
            self._queue.clear()
            self._timer = None

        print(f"Processing {len(contexts_to_process)} queued memory updates")

        try:
            updater = MemoryUpdater()

            for context in contexts_to_process:
                try:
                    print(f"Updating memory for thread {context.thread_id}")
                    success = updater.update_memory(
                        messages=context.messages,
                        thread_id=context.thread_id,
                        agent_name=context.agent_name,
                    )
                    if success:
                        print(f"Memory updated successfully for thread {context.thread_id}")
                    else:
                        print(f"Memory update skipped/failed for thread {context.thread_id}")
                except Exception as e:
                    print(f"Error updating memory for thread {context.thread_id}: {e}")

                # 更新之间的小延迟，以避免速率限制（Rate Limiting）
                if len(contexts_to_process) > 1:
                    time.sleep(0.5)

        finally:
            with self._lock:
                self._processing = False

    def flush(self) -> None:
        """强制立即处理队列。

        这对于测试或优雅关闭（Graceful Shutdown）很有用。
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        self._process_queue()

    def clear(self) -> None:
        """清空队列而不处理。

        这对于测试很有用。
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._queue.clear()
            self._processing = False

    @property
    def pending_count(self) -> int:
        """获取待处理更新的数量。"""
        with self._lock:
            return len(self._queue)

    @property
    def is_processing(self) -> bool:
        """检查队列当前是否正在被处理。"""
        with self._lock:
            return self._processing


# 全局单例实例（Singleton Instance）
_memory_queue: MemoryUpdateQueue | None = None
_queue_lock = threading.Lock()


def get_memory_queue() -> MemoryUpdateQueue:
    """获取全局记忆更新队列单例。

    Returns:
        记忆更新队列实例。
    """
    global _memory_queue
    with _queue_lock:
        if _memory_queue is None:
            _memory_queue = MemoryUpdateQueue()
        return _memory_queue


def reset_memory_queue() -> None:
    """重置全局记忆队列。

    这对于测试很有用。
    """
    global _memory_queue
    with _queue_lock:
        if _memory_queue is not None:
            _memory_queue.clear()
        _memory_queue = None
