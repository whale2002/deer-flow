"""用于记忆更新和注入的 Prompt 模板。"""

import re
from typing import Any

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# 基于对话更新记忆的 Prompt 模板
MEMORY_UPDATE_PROMPT = """你是一个记忆管理系统。你的任务是分析对话并更新用户的记忆档案。

  当前记忆状态：
  <current_memory>
  {current_memory}
  </current_memory>

  待处理的新对话：
  <conversation>
  {conversation}
  </conversation>

  指令：
  1. 分析对话中关于用户的重要信息
  2. 提取相关的事实、偏好和上下文，包含具体细节（数字、名称、技术）
  3. 根据以下详细的长度指南更新记忆部分

  记忆部分指南：

  **用户上下文**（当前状态 - 简洁摘要）：
  - workContext：职业角色、公司、关键项目、主要技术（2-3 句）
    示例：核心贡献者，带指标的项目名称（16k+ stars），技术栈
  - personalContext：语言、沟通偏好、关键兴趣（1-2 句）
    示例：双语能力、特定兴趣领域、专业领域
  - topOfMind：多个正在进行的关注点和优先级（3-5 句，详细段落）
    示例：主要项目工作并行的技术调查、持续的学习/跟踪
    包括：积极实现工作、问题排查、市场/研究兴趣
    注意：这记录的是几个并发的关注领域，而非单一任务

  **历史**（时间上下文 - 丰富的段落）：
  - recentMonths：近期活动的详细摘要（4-6 句或 1-2 段落）
    时间线：过去 1-3 个月的交互
    包括：探索的技术、进行的项目、解决的问题、展现的兴趣
  - earlierContext：重要的历史模式（3-5 句或 1 段落）
    时间线：3-12 个月前
    包括：过去的项目、学习历程、已建立的模式
  - longTermBackground：持久背景和基础上下文（2-4 句）
    时间线：整体/基础信息
    包括：核心专业知识、长期兴趣、基本工作风格

  **事实提取**：
  - 提取具体、可量化的细节（例如："16k+ GitHub stars"、"200+ datasets"）
  - 包含专有名词（公司名称、项目名称、技术名称）
  - 保留技术术语和版本号
  - 类别：
    * preference：工具、风格、用户偏好/厌恶的方法
    * knowledge：具体专业知识、掌握的技术领域知识
    * context：背景事实（职位头衔、项目、地点、语言）
    * behavior：工作模式、沟通习惯、解决问题的方法
    * goal：既定目标、学习目标、项目志向
  - 置信度级别：
    * 0.9-1.0：明确陈述的事实（"我从事 X"、"我的角色是 Y"）
    * 0.7-0.8：从行为/讨论中强烈暗示
    * 0.5-0.6：推断的模式（谨慎使用，仅用于明确的模式）

  **什么内容放哪里**：
  - workContext：当前工作、活跃项目、主要技术栈
  - personalContext：语言、性格、直接工作之外的兴趣
  - topOfMind：用户近期关心的多个持续优先级和关注领域（更新最频繁）
    应捕捉 3-5 个并发主题：主要工作、边角探索、学习/跟踪兴趣
  - recentMonths：近期技术探索和工作的详细描述
  - earlierContext：仍相关的稍早交互模式
  - longTermBackground：关于用户的不变基础事实

  **多语言内容**：
  - 为专有名词和公司名称保留原始语言
  - 保持技术术语的原始形式（DeepSeek、LangGraph 等）
  - 在 personalContext 中记录语言能力

  输出格式（JSON）：
  {{
    "user": {{
      "workContext": {{ "summary": "...", "shouldUpdate": true/false }},
      "personalContext": {{ "summary": "...", "shouldUpdate": true/false }},
      "topOfMind": {{ "summary": "...", "shouldUpdate": true/false }}
    }},
    "history": {{
      "recentMonths": {{ "summary": "...", "shouldUpdate": true/false }},
      "earlierContext": {{ "summary": "...", "shouldUpdate": true/false }},
      "longTermBackground": {{ "summary": "...", "shouldUpdate": true/false }}
    }},
    "newFacts": [
      {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
    ],
    "factsToRemove": ["fact_id_1", "fact_id_2"]
  }}

  重要规则：
  - 仅在有有意义的新信息时才设置 shouldUpdate=true
  - 遵循长度指南：workContext/personalContext 简洁（1-3 句），topOfMind 和 history 部分详细（段落）
  - 在事实中包含具体指标、版本号和专有名词
  - 只添加明确陈述（0.9+）或强烈暗示（0.7+）的事实
  - 移除被新信息矛盾的事实
  - 更新 topOfMind 时，整合新的关注领域同时移除已完成/放弃的
    保持 3-5 个仍活跃相关的并发关注主题
  - 对于 history 部分，按时间顺序将新信息整合到相应时间段
  - 保持技术准确性 - 保留技术、公司、项目的准确名称
  - 专注于对未来交互和个性化有用的信息
  - 重要提示：不要在记忆中记录文件上传事件。上传的文件是
    会话特定的且临时的 — 它们在未来的会话中不可访问。
    记录上传事件会导致后续对话中的混淆。

  仅返回有效的 JSON，无需解释或 markdown。"""


# 从单条消息中提取事实的 Prompt 模板
FACT_EXTRACTION_PROMPT = """从这条消息中提取关于用户的事实信息。

  消息：
  {message}

  按以下 JSON 格式提取事实：
  {{
    "facts": [
      {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
    ]
  }}

  类别：
  - preference：用户偏好（喜欢/厌恶、风格、工具）
  - knowledge：用户的专业知识或知识领域
  - context：背景上下文（地点、工作、项目）
  - behavior：行为模式
  - goal：用户的目标或目的

  规则：
  - 只提取清晰、具体的事实
  - 置信度应反映确定性（明确陈述 = 0.9+，暗示 = 0.6-0.8）
  - 跳过模糊或临时信息

  仅返回有效的 JSON。"""


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """使用 tiktoken 计算文本中的 token 数量。

    Args:
        text: 要计算 token 的文本。
        encoding_name: 使用的编码（默认为 cl100k_base，适用于 GPT-4/3.5）。

    Returns:
        文本中的 token 数量。
    """
    if not TIKTOKEN_AVAILABLE:
        # 如果 tiktoken 不可用，回退到基于字符的估算
        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        # 出错时回退到基于字符的估算
        return len(text) // 4


def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
    """格式化记忆数据以注入到系统 Prompt 中。

    Args:
        memory_data: 记忆数据字典。
        max_tokens: 使用的最大 token 数（通过 tiktoken 精确计数）。

    Returns:
        用于系统 Prompt 注入的格式化记忆字符串。
    """
    if not memory_data:
        return ""

    sections = []

    # 格式化用户上下文
    user_data = memory_data.get("user", {})
    if user_data:
        user_sections = []

        work_ctx = user_data.get("workContext", {})
        if work_ctx.get("summary"):
            user_sections.append(f"Work: {work_ctx['summary']}")

        personal_ctx = user_data.get("personalContext", {})
        if personal_ctx.get("summary"):
            user_sections.append(f"Personal: {personal_ctx['summary']}")

        top_of_mind = user_data.get("topOfMind", {})
        if top_of_mind.get("summary"):
            user_sections.append(f"Current Focus: {top_of_mind['summary']}")

        if user_sections:
            sections.append("User Context:\n" + "\n".join(f"- {s}" for s in user_sections))

    # 格式化历史
    history_data = memory_data.get("history", {})
    if history_data:
        history_sections = []

        recent = history_data.get("recentMonths", {})
        if recent.get("summary"):
            history_sections.append(f"Recent: {recent['summary']}")

        earlier = history_data.get("earlierContext", {})
        if earlier.get("summary"):
            history_sections.append(f"Earlier: {earlier['summary']}")

        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))

    if not sections:
        return ""

    result = "\n\n".join(sections)

    # 使用 tiktoken 进行精确的 token 计数
    token_count = _count_tokens(result)
    if token_count > max_tokens:
        # 截断以适应 token 限制
        # 基于 token 比例估算要删除的字符
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)  # 95% to leave margin
        result = result[:target_chars] + "\n..."

    return result


def format_conversation_for_update(messages: list[Any]) -> str:
    """为记忆更新 Prompt 格式化对话消息。

    Args:
        messages: 对话消息列表。

    Returns:
        格式化的对话字符串。
    """
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        # 处理可能是列表的内容（多模态 Multimodal）
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
            content = " ".join(text_parts) if text_parts else str(content)

        # 从人类消息中去除 uploaded_files 标签，以避免将临时文件路径信息持久化到长期记忆中。
        # 如果去除后不剩任何内容（仅上传消息），则跳过该轮次。
        if role == "human":
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue

        # 截断非常长的消息
        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
