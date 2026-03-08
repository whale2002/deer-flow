"""用于读取、写入和更新记忆数据的更新器。"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.agents.memory.prompt import (
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
)
from src.config.memory_config import get_memory_config
from src.config.paths import get_paths
from src.models import create_chat_model


def _get_memory_file_path(agent_name: str | None = None) -> Path:
    """获取记忆文件的路径。

    Args:
        agent_name: 如果提供，则返回该 Agent 的记忆文件路径。
                    如果为 None，则返回全局记忆文件路径。

    Returns:
        记忆文件的路径。
    """
    if agent_name is not None:
        return get_paths().agent_memory_file(agent_name)

    config = get_memory_config()
    if config.storage_path:
        p = Path(config.storage_path)
        # 绝对路径：原样使用；相对路径：基于 base_dir 解析
        return p if p.is_absolute() else get_paths().base_dir / p
    return get_paths().memory_file


def _create_empty_memory() -> dict[str, Any]:
    """创建一个空的记忆结构（Schema）。"""
    return {
        "version": "1.0",
        "lastUpdated": datetime.utcnow().isoformat() + "Z",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


# 每个 Agent 的记忆缓存：以 agent_name 为键（None 表示全局）
# 值：(memory_data, file_mtime)
_memory_cache: dict[str | None, tuple[dict[str, Any], float | None]] = {}


def get_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """获取当前的记忆数据（带文件修改时间检查的缓存）。

    如果记忆文件自上次加载以来已被修改，缓存会自动失效（Invalidate），
    以确保始终返回最新数据（类似于 HTTP 协商缓存）。

    Args:
        agent_name: 如果提供，加载该 Agent 的记忆。如果为 None，加载全局记忆。

    Returns:
        记忆数据字典（Object）。
    """
    file_path = _get_memory_file_path(agent_name)

    # 获取当前文件修改时间
    try:
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        current_mtime = None

    cached = _memory_cache.get(agent_name)

    # 如果文件已被修改或不存在，则使缓存失效
    if cached is None or cached[1] != current_mtime:
        memory_data = _load_memory_from_file(agent_name)
        _memory_cache[agent_name] = (memory_data, current_mtime)
        return memory_data

    return cached[0]


def reload_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """从文件重新加载记忆数据，强制使缓存失效。

    Args:
        agent_name: 如果提供，重新加载该 Agent 的记忆。如果为 None，重新加载全局记忆。

    Returns:
        重新加载的记忆数据字典。
    """
    file_path = _get_memory_file_path(agent_name)
    memory_data = _load_memory_from_file(agent_name)

    try:
        mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        mtime = None

    _memory_cache[agent_name] = (memory_data, mtime)
    return memory_data


def _load_memory_from_file(agent_name: str | None = None) -> dict[str, Any]:
    """从文件加载记忆数据。

    Args:
        agent_name: 如果提供，加载该 Agent 的记忆文件。如果为 None，加载全局。

    Returns:
        记忆数据字典。
    """
    file_path = _get_memory_file_path(agent_name)

    if not file_path.exists():
        return _create_empty_memory()

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"Failed to load memory file: {e}")
        return _create_empty_memory()


# 匹配描述文件上传“事件”而非一般文件相关工作的句子。
# 故意缩小范围以避免删除合法事实，例如“用户使用 CSV 文件”或“偏好 PDF 导出”。
_UPLOAD_SENTENCE_RE = re.compile(
    r"[^.!?]*\b(?:"
    r"upload(?:ed|ing)?(?:\s+\w+){0,3}\s+(?:file|files?|document|documents?|attachment|attachments?)"
    r"|file\s+upload"
    r"|/mnt/user-data/uploads/"
    r"|<uploaded_files>"
    r")[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)


def _strip_upload_mentions_from_memory(memory_data: dict[str, Any]) -> dict[str, Any]:
    """从所有记忆摘要和事实中删除有关文件上传的句子。

    上传的文件是会话范围（Session Scoped）的；将上传事件持久化到长期记忆中，
    会导致 Agent 在未来的会话中搜索不存在的文件。
    """
    # 清理 user/history 部分的摘要
    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", val["summary"]).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned

    # 同时删除任何描述上传事件的事实
    facts = memory_data.get("facts", [])
    if facts:
        memory_data["facts"] = [f for f in facts if not _UPLOAD_SENTENCE_RE.search(f.get("content", ""))]

    return memory_data


def _save_memory_to_file(memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
    """将记忆数据保存到文件并更新缓存。

    Args:
        memory_data: 要保存的记忆数据。
        agent_name: 如果提供，保存到该 Agent 的记忆文件。如果为 None，保存到全局。

    Returns:
        成功返回 True，否则返回 False。
    """
    file_path = _get_memory_file_path(agent_name)

    try:
        # 确保目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 更新 lastUpdated 时间戳
        memory_data["lastUpdated"] = datetime.utcnow().isoformat() + "Z"

        # 使用临时文件进行原子写入（Atomic Write）
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        # 将临时文件重命名为实际文件（在大多数系统上是原子操作）
        temp_path.replace(file_path)

        # 更新缓存和文件修改时间
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = None

        _memory_cache[agent_name] = (memory_data, mtime)

        print(f"Memory saved to {file_path}")
        return True
    except OSError as e:
        print(f"Failed to save memory file: {e}")
        return False


class MemoryUpdater:
    """基于对话上下文使用 LLM 更新记忆。"""

    def __init__(self, model_name: str | None = None):
        """初始化记忆更新器。

        Args:
            model_name: 可选的模型名称。如果为 None，则使用配置或默认值。
        """
        self._model_name = model_name

    def _get_model(self):
        """获取用于记忆更新的模型。"""
        config = get_memory_config()
        model_name = self._model_name or config.model_name
        return create_chat_model(name=model_name, thinking_enabled=False)

    def update_memory(self, messages: list[Any], thread_id: str | None = None, agent_name: str | None = None) -> bool:
        """基于对话消息更新记忆。

        Args:
            messages: 对话消息列表。
            thread_id: 用于追踪来源的可选线程 ID。
            agent_name: 如果提供，更新该 Agent 的记忆。如果为 None，更新全局记忆。

        Returns:
            如果更新成功返回 True，否则返回 False。
        """
        config = get_memory_config()
        if not config.enabled:
            return False

        if not messages:
            return False

        try:
            # 获取当前记忆
            current_memory = get_memory_data(agent_name)

            # 格式化对话用于 Prompt
            conversation_text = format_conversation_for_update(messages)

            if not conversation_text.strip():
                return False

            # 构建 Prompt
            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current_memory, indent=2),
                conversation=conversation_text,
            )

            # 调用 LLM
            model = self._get_model()
            response = model.invoke(prompt)
            response_text = str(response.content).strip()

            # 解析响应
            # 如果存在，移除 Markdown 代码块
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            update_data = json.loads(response_text)

            # 应用更新
            updated_memory = self._apply_updates(current_memory, update_data, thread_id)

            # 保存前从所有摘要中删除文件上传提及。
            # 上传的文件是会话范围的，在未来的会话中将不存在，
            # 因此在长期记忆中记录上传事件会导致 Agent 在后续对话中
            # 尝试（并失败）定位这些文件。
            updated_memory = _strip_upload_mentions_from_memory(updated_memory)

            # 保存
            return _save_memory_to_file(updated_memory, agent_name)

        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response for memory update: {e}")
            return False
        except Exception as e:
            print(f"Memory update failed: {e}")
            return False

    def _apply_updates(
        self,
        current_memory: dict[str, Any],
        update_data: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """将 LLM 生成的更新应用到记忆中（类似于 Redux Reducer）。

        Args:
            current_memory: 当前记忆数据。
            update_data: 来自 LLM 的更新数据。
            thread_id: 用于追踪的可选线程 ID。

        Returns:
            更新后的记忆数据。
        """
        config = get_memory_config()
        now = datetime.utcnow().isoformat() + "Z"

        # 更新用户部分
        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # 更新历史部分
        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # 移除事实
        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

        # 添加新事实
        new_facts = update_data.get("newFacts", [])
        for fact in new_facts:
            confidence = fact.get("confidence", 0.5)
            if confidence >= config.fact_confidence_threshold:
                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": fact.get("content", ""),
                    "category": fact.get("category", "context"),
                    "confidence": confidence,
                    "createdAt": now,
                    "source": thread_id or "unknown",
                }
                current_memory["facts"].append(fact_entry)

        # 强制执行最大事实数量限制
        if len(current_memory["facts"]) > config.max_facts:
            # 按置信度排序并保留排名靠前的
            current_memory["facts"] = sorted(
                current_memory["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]

        return current_memory


def update_memory_from_conversation(messages: list[Any], thread_id: str | None = None, agent_name: str | None = None) -> bool:
    """从对话更新记忆的便捷函数（Helper Function）。

    Args:
        messages: 对话消息列表。
        thread_id: 可选线程 ID。
        agent_name: 如果提供，更新该 Agent 的记忆。如果为 None，更新全局记忆。

    Returns:
        如果成功返回 True，否则返回 False。
    """
    updater = MemoryUpdater()
    return updater.update_memory(messages, thread_id, agent_name)
