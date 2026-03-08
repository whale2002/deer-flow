import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config.app_config import get_app_config
from src.gateway.config import get_gateway_config
from src.gateway.routers import (
    agents,
    artifacts,
    channels,
    mcp,
    memory,
    models,
    skills,
    suggestions,
    uploads,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用程序生命周期处理程序。"""

    # 启动时加载配置并检查必要的环境变量
    try:
        get_app_config()
        logger.info("配置加载成功")
    except Exception as e:
        error_msg = f"网关启动期间加载配置失败: {e}"
        logger.exception(error_msg)
        raise RuntimeError(error_msg) from e
    config = get_gateway_config()
    logger.info(f"正在 {config.host}:{config.port} 上启动 API 网关")

    # 注意：MCP 工具初始化不在这里进行，因为：
    # 1. 网关不使用 MCP 工具 - 它们由 LangGraph Server 中的 Agent 使用
    # 2. 网关和 LangGraph Server 是具有独立缓存的单独进程
    # MCP 工具在 LangGraph Server 中首次需要时懒加载初始化

    # 如果配置了任何频道，则启动 IM 频道服务
    try:
        from src.channels.service import start_channel_service

        channel_service = await start_channel_service()
        logger.info("频道服务已启动: %s", channel_service.get_status())
    except Exception:
        logger.exception("未配置 IM 频道或频道服务启动失败")

    yield

    # 关闭时停止频道服务
    try:
        from src.channels.service import stop_channel_service

        await stop_channel_service()
    except Exception:
        logger.exception("停止频道服务失败")
    logger.info("正在关闭 API 网关")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用程序。

    Returns:
        配置好的 FastAPI 应用程序实例。
    """

    app = FastAPI(
        title="DeerFlow API Gateway",
        description="""
## DeerFlow API 网关

DeerFlow 的 API 网关 - 基于 LangGraph 的具有沙箱执行能力的 AI Agent 后端。

### 功能特性

- **模型管理**：查询和检索可用的 AI 模型
- **MCP 配置**：管理模型上下文协议（MCP）服务器配置
- **记忆管理**：访问和管理全局记忆数据以进行个性化对话
- **技能管理**：查询和管理技能及其启用状态
- **产物管理**：访问和下载线程产物及生成的文件
- **健康监控**：系统健康检查端点

### 架构

LangGraph 请求由 nginx 反向代理处理。
此网关为模型、MCP 配置、技能和产物提供自定义端点。
        """,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {
                "name": "models",
                "description": "查询可用 AI 模型及其配置的操作",
            },
            {
                "name": "mcp",
                "description": "管理模型上下文协议（MCP）服务器配置",
            },
            {
                "name": "memory",
                "description": "访问和管理全局记忆数据以进行个性化对话",
            },
            {
                "name": "skills",
                "description": "管理技能及其配置",
            },
            {
                "name": "artifacts",
                "description": "访问和下载线程产物及生成的文件",
            },
            {
                "name": "uploads",
                "description": "上传和管理线程的用户文件",
            },
            {
                "name": "agents",
                "description": "创建和管理具有每个 Agent 配置和提示词的自定义 Agent",
            },
            {
                "name": "suggestions",
                "description": "为对话生成后续问题建议",
            },
            {
                "name": "channels",
                "description": "管理 IM 频道集成（飞书、Slack、Telegram）",
            },
            {
                "name": "health",
                "description": "健康检查和系统状态端点",
            },
        ],
    )

    # CORS 由 nginx 处理 - 不需要 FastAPI 中间件

    # 包含路由
    # Models API 挂载在 /api/models
    app.include_router(models.router)

    # MCP API 挂载在 /api/mcp
    app.include_router(mcp.router)

    # Memory API 挂载在 /api/memory
    app.include_router(memory.router)

    # Skills API 挂载在 /api/skills
    app.include_router(skills.router)

    # Artifacts API 挂载在 /api/threads/{thread_id}/artifacts
    app.include_router(artifacts.router)

    # Uploads API 挂载在 /api/threads/{thread_id}/uploads
    app.include_router(uploads.router)

    # Agents API 挂载在 /api/agents
    app.include_router(agents.router)

    # Suggestions API 挂载在 /api/threads/{thread_id}/suggestions
    app.include_router(suggestions.router)

    # Channels API 挂载在 /api/channels
    app.include_router(channels.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict:
        """健康检查端点。

        Returns:
            服务健康状态信息。
        """
        return {"status": "healthy", "service": "deer-flow-gateway"}

    return app


# 为 uvicorn 创建应用实例
app = create_app()
