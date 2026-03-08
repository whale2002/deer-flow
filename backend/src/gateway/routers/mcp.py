import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mcp"])


class McpOAuthConfigResponse(BaseModel):
    """MCP 服务器的 OAuth 配置。"""

    enabled: bool = Field(default=True, description="是否启用 OAuth 令牌注入")
    token_url: str = Field(default="", description="OAuth 令牌端点 URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(default="client_credentials", description="OAuth 授权类型")
    client_id: str | None = Field(default=None, description="OAuth 客户端 ID")
    client_secret: str | None = Field(default=None, description="OAuth 客户端密钥")
    refresh_token: str | None = Field(default=None, description="OAuth 刷新令牌")
    scope: str | None = Field(default=None, description="OAuth 作用域 (Scope)")
    audience: str | None = Field(default=None, description="OAuth 受众 (Audience)")
    token_field: str = Field(default="access_token", description="包含访问令牌的响应字段名")
    token_type_field: str = Field(default="token_type", description="包含令牌类型的响应字段名")
    expires_in_field: str = Field(default="expires_in", description="包含过期时间的响应字段名 (秒)")
    default_token_type: str = Field(default="Bearer", description="当响应省略 token_type 时的默认令牌类型")
    refresh_skew_seconds: int = Field(default=60, description="在过期前多少秒进行刷新")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="发送到令牌端点的额外表单参数")


class McpServerConfigResponse(BaseModel):
    """MCP 服务器配置的响应模型。"""

    enabled: bool = Field(default=True, description="是否启用此 MCP 服务器")
    type: str = Field(default="stdio", description="传输类型: 'stdio', 'sse', 或 'http'")
    command: str | None = Field(default=None, description="启动 MCP 服务器的命令 (仅限 stdio 类型)")
    args: list[str] = Field(default_factory=list, description="传递给命令的参数 (仅限 stdio 类型)")
    env: dict[str, str] = Field(default_factory=dict, description="MCP 服务器的环境变量")
    url: str | None = Field(default=None, description="MCP 服务器的 URL (仅限 sse 或 http 类型)")
    headers: dict[str, str] = Field(default_factory=dict, description="发送的 HTTP 标头 (仅限 sse 或 http 类型)")
    oauth: McpOAuthConfigResponse | None = Field(default=None, description="MCP HTTP/SSE 服务器的 OAuth 配置")
    description: str = Field(default="", description="此 MCP 服务器提供功能的易读描述")


class McpConfigResponse(BaseModel):
    """MCP 配置的响应模型。"""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="MCP 服务器名称到配置的映射",
    )


class McpConfigUpdateRequest(BaseModel):
    """更新 MCP 配置的请求模型。"""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        ...,
        description="MCP 服务器名称到配置的映射",
    )


@router.get(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="获取 MCP 配置",
    description="检索当前的模型上下文协议 (MCP) 服务器配置。",
)
async def get_mcp_configuration() -> McpConfigResponse:
    """获取当前的 MCP 配置。

    Returns:
        包含所有服务器的当前 MCP 配置。

    Example:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_xxx"},
                    "description": "用于仓库操作的 GitHub MCP 服务器"
                }
            }
        }
        ```
    """
    config = get_extensions_config()

    return McpConfigResponse(mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in config.mcp_servers.items()})


@router.put(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="更新 MCP 配置",
    description="更新模型上下文协议 (MCP) 服务器配置并保存到文件。",
)
async def update_mcp_configuration(request: McpConfigUpdateRequest) -> McpConfigResponse:
    """更新 MCP 配置。

    此操作将：
    1. 将新配置保存到 mcp_config.json 文件
    2. 重新加载配置缓存
    3. 重置 MCP 工具缓存以触发重新初始化

    Args:
        request: 要保存的新 MCP 配置。

    Returns:
        更新后的 MCP 配置。

    Raises:
        HTTPException: 如果无法写入配置文件，返回 500 错误。

    Example Request:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                    "description": "用于仓库操作的 GitHub MCP 服务器"
                }
            }
        }
        ```
    """
    try:
        # 获取当前配置路径 (或确定保存位置)
        config_path = ExtensionsConfig.resolve_config_path()

        # 如果不存在配置文件，则在父目录 (项目根目录) 中创建一个
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info(f"未找到现有的扩展配置。在以下位置创建新配置: {config_path}")

        # 加载当前配置以保留 skills 配置
        current_config = get_extensions_config()

        # 将请求转换为 dict 格式以进行 JSON 序列化
        config_data = {
            "mcpServers": {name: server.model_dump() for name, server in request.mcp_servers.items()},
            "skills": {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()},
        }

        # 将配置写入文件
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"MCP configuration updated and saved to: {config_path}")

        # 注意：此处无需重新加载/重置缓存 - LangGraph Server (独立进程)
        # 会通过 mtime 检测配置文件更改并自动重新初始化 MCP 工具

        # 重新加载配置并更新全局缓存
        reloaded_config = reload_extensions_config()
        return McpConfigResponse(mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in reloaded_config.mcp_servers.items()})

    except Exception as e:
        logger.error(f"Failed to update MCP configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新 MCP 配置失败: {str(e)}")
