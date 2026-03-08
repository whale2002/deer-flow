"""建议路由器。"""

import json
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.models import create_chat_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["suggestions"])


class SuggestionMessage(BaseModel):
    """用于生成建议的消息。"""

    role: str = Field(..., description="消息角色：user|assistant")
    content: str = Field(..., description="纯文本消息内容")


class SuggestionsRequest(BaseModel):
    """生成建议的请求。"""

    messages: list[SuggestionMessage] = Field(..., description="最近的对话消息")
    n: int = Field(default=3, ge=1, le=5, description="要生成的建议数量")
    model_name: str | None = Field(default=None, description="可选的模型覆盖")


class SuggestionsResponse(BaseModel):
    """生成的建议响应。"""

    suggestions: list[str] = Field(default_factory=list, description="建议的后续问题")


def _strip_markdown_code_fence(text: str) -> str:
    """去除 Markdown 代码块标记（如果存在）。"""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_json_string_list(text: str) -> list[str] | None:
    """尝试将文本解析为 JSON 字符串列表。"""
    candidate = _strip_markdown_code_fence(text)
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    out: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        out.append(s)
    return out


def _format_conversation(messages: list[SuggestionMessage]) -> str:
    """将消息格式化为对话字符串。"""
    parts: list[str] = []
    for m in messages:
        role = m.role.strip().lower()
        if role in ("user", "human"):
            parts.append(f"User: {m.content.strip()}")
        elif role in ("assistant", "ai"):
            parts.append(f"Assistant: {m.content.strip()}")
        else:
            parts.append(f"{m.role}: {m.content.strip()}")
    return "\n".join(parts).strip()


@router.post(
    "/threads/{thread_id}/suggestions",
    response_model=SuggestionsResponse,
    summary="生成后续问题",
    description="基于最近的对话上下文，生成用户接下来可能提出的简短后续问题。",
)
async def generate_suggestions(thread_id: str, request: SuggestionsRequest) -> SuggestionsResponse:
    """生成对话建议。

    使用 LLM 分析对话历史并建议相关的后续问题。

    Args:
        thread_id: 线程 ID（用于日志记录）。
        request: 包含消息历史的请求。

    Returns:
        建议的问题列表。
    """
    if not request.messages:
        return SuggestionsResponse(suggestions=[])

    n = request.n
    conversation = _format_conversation(request.messages)
    if not conversation:
        return SuggestionsResponse(suggestions=[])

    prompt = (
        "You are generating follow-up questions to help the user continue the conversation.\n"
        f"Based on the conversation below, produce EXACTLY {n} short questions the user might ask next.\n"
        "Requirements:\n"
        "- Questions must be relevant to the conversation.\n"
        "- Questions must be written in the same language as the user.\n"
        "- Keep each question concise (ideally <= 20 words / <= 40 Chinese characters).\n"
        "- Do NOT include numbering, markdown, or any extra text.\n"
        "- Output MUST be a JSON array of strings only.\n\n"
        "Conversation:\n"
        f"{conversation}\n"
    ).format(n=n, conversation=conversation)

    try:
        model = create_chat_model(name=request.model_name, thinking_enabled=False)
        response = model.invoke(prompt)
        raw = str(response.content or "")
        suggestions = _parse_json_string_list(raw) or []
        cleaned = [s.replace("\n", " ").strip() for s in suggestions if s.strip()]
        cleaned = cleaned[:n]
        return SuggestionsResponse(suggestions=cleaned)
    except Exception as exc:
        logger.exception("Failed to generate suggestions: thread_id=%s err=%s", thread_id, exc)
        return SuggestionsResponse(suggestions=[])
