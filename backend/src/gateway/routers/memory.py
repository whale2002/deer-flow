"""用于检索和管理全局记忆数据的 Memory API 路由。"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.agents.memory.updater import get_memory_data, reload_memory_data
from src.config.memory_config import get_memory_config

router = APIRouter(prefix="/api", tags=["memory"])


class ContextSection(BaseModel):
    """上下文部分模型 (用户和历史)。"""

    summary: str = Field(default="", description="摘要内容")
    updatedAt: str = Field(default="", description="最后更新时间戳")


class UserContext(BaseModel):
    """用户上下文模型。"""

    workContext: ContextSection = Field(default_factory=ContextSection)
    personalContext: ContextSection = Field(default_factory=ContextSection)
    topOfMind: ContextSection = Field(default_factory=ContextSection)


class HistoryContext(BaseModel):
    """历史上下文模型。"""

    recentMonths: ContextSection = Field(default_factory=ContextSection)
    earlierContext: ContextSection = Field(default_factory=ContextSection)
    longTermBackground: ContextSection = Field(default_factory=ContextSection)


class Fact(BaseModel):
    """记忆事实模型。"""

    id: str = Field(..., description="事实的唯一标识符")
    content: str = Field(..., description="事实内容")
    category: str = Field(default="context", description="事实分类")
    confidence: float = Field(default=0.5, description="置信度分数 (0-1)")
    createdAt: str = Field(default="", description="创建时间戳")
    source: str = Field(default="unknown", description="来源线程 ID")


class MemoryResponse(BaseModel):
    """记忆数据响应模型。"""

    version: str = Field(default="1.0", description="记忆 Schema 版本")
    lastUpdated: str = Field(default="", description="最后更新时间戳")
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)


class MemoryConfigResponse(BaseModel):
    """记忆配置响应模型。"""

    enabled: bool = Field(..., description="是否启用记忆功能")
    storage_path: str = Field(..., description="记忆存储文件路径")
    debounce_seconds: int = Field(..., description="记忆更新的防抖时间 (秒)")
    max_facts: int = Field(..., description="存储的最大事实数量")
    fact_confidence_threshold: float = Field(..., description="事实的最低置信度阈值")
    injection_enabled: bool = Field(..., description="是否启用记忆注入")
    max_injection_tokens: int = Field(..., description="记忆注入的最大 Token 数")


class MemoryStatusResponse(BaseModel):
    """记忆状态响应模型。"""

    config: MemoryConfigResponse
    data: MemoryResponse


@router.get(
    "/memory",
    response_model=MemoryResponse,
    summary="获取记忆数据",
    description="检索当前的全局记忆数据，包括用户上下文、历史记录和事实。",
)
async def get_memory() -> MemoryResponse:
    """获取当前的全局记忆数据。

    Returns:
        包含用户上下文、历史记录和事实的当前记忆数据。

    Example Response:
        ```json
        {
            "version": "1.0",
            "lastUpdated": "2024-01-15T10:30:00Z",
            "user": {
                "workContext": {"summary": "Working on DeerFlow project", "updatedAt": "..."},
                "personalContext": {"summary": "Prefers concise responses", "updatedAt": "..."},
                "topOfMind": {"summary": "Building memory API", "updatedAt": "..."}
            },
            "history": {
                "recentMonths": {"summary": "Recent development activities", "updatedAt": "..."},
                "earlierContext": {"summary": "", "updatedAt": ""},
                "longTermBackground": {"summary": "", "updatedAt": ""}
            },
            "facts": [
                {
                    "id": "fact_abc123",
                    "content": "User prefers TypeScript over JavaScript",
                    "category": "preference",
                    "confidence": 0.9,
                    "createdAt": "2024-01-15T10:30:00Z",
                    "source": "thread_xyz"
                }
            ]
        }
        ```
    """
    memory_data = get_memory_data()
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/reload",
    response_model=MemoryResponse,
    summary="重新加载记忆数据",
    description="从存储文件中重新加载记忆数据，刷新内存缓存。",
)
async def reload_memory() -> MemoryResponse:
    """从文件重新加载记忆数据。

    当文件在外部被修改时，此操作强制从存储文件中重新加载记忆数据。

    Returns:
        重新加载后的记忆数据。
    """
    memory_data = reload_memory_data()
    return MemoryResponse(**memory_data)


@router.get(
    "/memory/config",
    response_model=MemoryConfigResponse,
    summary="获取记忆配置",
    description="检索当前的记忆系统配置。",
)
async def get_memory_config_endpoint() -> MemoryConfigResponse:
    """获取记忆系统配置。

    Returns:
        当前的记忆配置设置。

    Example Response:
        ```json
        {
            "enabled": true,
            "storage_path": ".deer-flow/memory.json",
            "debounce_seconds": 30,
            "max_facts": 100,
            "fact_confidence_threshold": 0.7,
            "injection_enabled": true,
            "max_injection_tokens": 2000
        }
        ```
    """
    config = get_memory_config()
    return MemoryConfigResponse(
        enabled=config.enabled,
        storage_path=config.storage_path,
        debounce_seconds=config.debounce_seconds,
        max_facts=config.max_facts,
        fact_confidence_threshold=config.fact_confidence_threshold,
        injection_enabled=config.injection_enabled,
        max_injection_tokens=config.max_injection_tokens,
    )


@router.get(
    "/memory/status",
    response_model=MemoryStatusResponse,
    summary="获取记忆状态",
    description="在一次请求中同时检索记忆配置和当前数据。",
)
async def get_memory_status() -> MemoryStatusResponse:
    """获取记忆系统状态，包括配置和数据。

    Returns:
        组合的记忆配置和当前数据。
    """
    config = get_memory_config()
    memory_data = get_memory_data()

    return MemoryStatusResponse(
        config=MemoryConfigResponse(
            enabled=config.enabled,
            storage_path=config.storage_path,
            debounce_seconds=config.debounce_seconds,
            max_facts=config.max_facts,
            fact_confidence_threshold=config.fact_confidence_threshold,
            injection_enabled=config.injection_enabled,
            max_injection_tokens=config.max_injection_tokens,
        ),
        data=MemoryResponse(**memory_data),
    )
