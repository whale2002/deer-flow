"""自定义 Agent 的增删改查 API。"""

import logging
import re
import shutil

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.agents_config import AgentConfig, list_custom_agents, load_agent_config, load_agent_soul
from src.config.paths import get_paths

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["agents"])

# Agent 名称的正则表达式：仅允许字母、数字和连字符
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentResponse(BaseModel):
    """自定义 Agent 的响应模型 (DTO)。"""

    name: str = Field(..., description="Agent 名称 (连字符命名法)")
    description: str = Field(default="", description="Agent 描述")
    model: str | None = Field(default=None, description="可选的模型覆盖配置")
    tool_groups: list[str] | None = Field(default=None, description="可选的工具组白名单")
    soul: str | None = Field(default=None, description="SOUL.md 内容 (在 GET /{name} 时包含)")


class AgentsListResponse(BaseModel):
    """列出所有自定义 Agent 的响应模型。"""

    agents: list[AgentResponse]


class AgentCreateRequest(BaseModel):
    """创建自定义 Agent 的请求体。"""

    name: str = Field(..., description="Agent 名称 (必须匹配 ^[A-Za-z0-9-]+$，存储时会转为小写)")
    description: str = Field(default="", description="Agent 描述")
    model: str | None = Field(default=None, description="可选的模型覆盖配置")
    tool_groups: list[str] | None = Field(default=None, description="可选的工具组白名单")
    soul: str = Field(default="", description="SOUL.md 内容 — 定义 Agent 的人设和行为准则")


class AgentUpdateRequest(BaseModel):
    """更新自定义 Agent 的请求体。"""

    description: str | None = Field(default=None, description="更新后的描述")
    model: str | None = Field(default=None, description="更新后的模型覆盖配置")
    tool_groups: list[str] | None = Field(default=None, description="更新后的工具组白名单")
    soul: str | None = Field(default=None, description="更新后的 SOUL.md 内容")


def _validate_agent_name(name: str) -> None:
    """验证 Agent 名称是否符合规则。

    Args:
        name: 待验证的 Agent 名称。

    Raises:
        HTTPException: 如果名称无效，返回 422 错误。
    """
    if not AGENT_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=422,
            detail=f"Agent 名称 '{name}' 无效。必须匹配 ^[A-Za-z0-9-]+$ (仅限字母、数字和连字符)。",
        )


def _normalize_agent_name(name: str) -> str:
    """将 Agent 名称标准化为小写，以便在文件系统中存储。"""
    return name.lower()


def _agent_config_to_response(agent_cfg: AgentConfig, include_soul: bool = False) -> AgentResponse:
    """将 AgentConfig 对象转换为 AgentResponse 对象 (DTO 转换)。"""
    soul: str | None = None
    if include_soul:
        soul = load_agent_soul(agent_cfg.name) or ""

    return AgentResponse(
        name=agent_cfg.name,
        description=agent_cfg.description,
        model=agent_cfg.model,
        tool_groups=agent_cfg.tool_groups,
        soul=soul,
    )


@router.get(
    "/agents",
    response_model=AgentsListResponse,
    summary="获取自定义 Agent 列表",
    description="列出 agents 目录下所有可用的自定义 Agent。",
)
async def list_agents() -> AgentsListResponse:
    """列出所有自定义 Agent。

    Returns:
        包含所有自定义 Agent 元数据的列表 (不包含 soul 内容)。
    """
    try:
        agents = list_custom_agents()
        return AgentsListResponse(agents=[_agent_config_to_response(a) for a in agents])
    except Exception as e:
        logger.error(f"Failed to list agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取 Agent 列表失败: {str(e)}")


@router.get(
    "/agents/check",
    summary="检查 Agent 名称可用性",
    description="验证 Agent 名称格式并检查是否已被占用 (不区分大小写)。",
)
async def check_agent_name(name: str) -> dict:
    """检查 Agent 名称是否有效且未被占用。

    Args:
        name: 待检查的 Agent 名称。

    Returns:
        ``{"available": true/false, "name": "<normalized>"}``

    Raises:
        HTTPException: 如果名称无效，返回 422 错误。
    """
    _validate_agent_name(name)
    normalized = _normalize_agent_name(name)
    # 检查对应目录是否存在
    available = not get_paths().agent_dir(normalized).exists()
    return {"available": available, "name": normalized}


@router.get(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="获取单个自定义 Agent",
    description="获取特定自定义 Agent 的详情和 SOUL.md 内容。",
)
async def get_agent(name: str) -> AgentResponse:
    """根据名称获取特定的自定义 Agent。

    Args:
        name: Agent 名称。

    Returns:
        Agent 详情 (包含 SOUL.md 内容)。

    Raises:
        HTTPException: 如果找不到 Agent，返回 404 错误。
    """
    _validate_agent_name(name)
    name = _normalize_agent_name(name)

    try:
        agent_cfg = load_agent_config(name)
        return _agent_config_to_response(agent_cfg, include_soul=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"未找到 Agent '{name}'")
    except Exception as e:
        logger.error(f"Failed to get agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取 Agent 失败: {str(e)}")


@router.post(
    "/agents",
    response_model=AgentResponse,
    status_code=201,
    summary="创建自定义 Agent",
    description="创建一个新的自定义 Agent，包含其配置和 SOUL.md。",
)
async def create_agent_endpoint(request: AgentCreateRequest) -> AgentResponse:
    """创建一个新的自定义 Agent。

    Args:
        request: 创建 Agent 的请求体。

    Returns:
        创建成功的 Agent 详情。

    Raises:
        HTTPException: 如果 Agent 已存在返回 409，名称无效返回 422。
    """
    _validate_agent_name(request.name)
    normalized_name = _normalize_agent_name(request.name)

    agent_dir = get_paths().agent_dir(normalized_name)

    if agent_dir.exists():
        raise HTTPException(status_code=409, detail=f"Agent '{normalized_name}' 已存在")

    try:
        # 创建 Agent 目录
        agent_dir.mkdir(parents=True, exist_ok=True)

        # 写入 config.yaml 配置文件
        config_data: dict = {"name": normalized_name}
        if request.description:
            config_data["description"] = request.description
        if request.model is not None:
            config_data["model"] = request.model
        if request.tool_groups is not None:
            config_data["tool_groups"] = request.tool_groups

        config_file = agent_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        # 写入 SOUL.md 人设文件
        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text(request.soul, encoding="utf-8")

        logger.info(f"Created agent '{normalized_name}' at {agent_dir}")

        agent_cfg = load_agent_config(normalized_name)
        return _agent_config_to_response(agent_cfg, include_soul=True)

    except HTTPException:
        raise
    except Exception as e:
        # 失败时清理已创建的目录
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        logger.error(f"Failed to create agent '{request.name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建 Agent 失败: {str(e)}")


@router.put(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="更新自定义 Agent",
    description="更新现有自定义 Agent 的配置和/或 SOUL.md。",
)
async def update_agent(name: str, request: AgentUpdateRequest) -> AgentResponse:
    """更新现有的自定义 Agent。

    Args:
        name: Agent 名称。
        request: 更新请求体 (所有字段均为可选)。

    Returns:
        更新后的 Agent 详情。

    Raises:
        HTTPException: 如果找不到 Agent，返回 404 错误。
    """
    _validate_agent_name(name)
    name = _normalize_agent_name(name)

    try:
        agent_cfg = load_agent_config(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"未找到 Agent '{name}'")

    agent_dir = get_paths().agent_dir(name)

    try:
        # 如果有任何配置字段变更，则更新 config.yaml
        config_changed = any(v is not None for v in [request.description, request.model, request.tool_groups])

        if config_changed:
            updated: dict = {
                "name": agent_cfg.name,
                "description": request.description if request.description is not None else agent_cfg.description,
            }
            new_model = request.model if request.model is not None else agent_cfg.model
            if new_model is not None:
                updated["model"] = new_model

            new_tool_groups = request.tool_groups if request.tool_groups is not None else agent_cfg.tool_groups
            if new_tool_groups is not None:
                updated["tool_groups"] = new_tool_groups

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(updated, f, default_flow_style=False, allow_unicode=True)

        # 如果提供了 soul 内容，则更新 SOUL.md
        if request.soul is not None:
            soul_path = agent_dir / "SOUL.md"
            soul_path.write_text(request.soul, encoding="utf-8")

        logger.info(f"Updated agent '{name}'")

        refreshed_cfg = load_agent_config(name)
        return _agent_config_to_response(refreshed_cfg, include_soul=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新 Agent 失败: {str(e)}")


class UserProfileResponse(BaseModel):
    """全局用户画像 (USER.md) 的响应模型。"""

    content: str | None = Field(default=None, description="USER.md 内容，如果尚未创建则为 null")


class UserProfileUpdateRequest(BaseModel):
    """设置全局用户画像的请求体。"""

    content: str = Field(default="", description="USER.md 内容 — 描述用户的背景和偏好")


@router.get(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="获取用户画像",
    description="读取注入到所有自定义 Agent 中的全局 USER.md 文件。",
)
async def get_user_profile() -> UserProfileResponse:
    """返回当前的 USER.md 内容。

    Returns:
        UserProfileResponse，如果 USER.md 不存在则 content=None。
    """
    try:
        user_md_path = get_paths().user_md_file
        if not user_md_path.exists():
            return UserProfileResponse(content=None)
        raw = user_md_path.read_text(encoding="utf-8").strip()
        return UserProfileResponse(content=raw or None)
    except Exception as e:
        logger.error(f"Failed to read user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取用户画像失败: {str(e)}")


@router.put(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="更新用户画像",
    description="写入全局 USER.md 文件，该文件会注入到所有自定义 Agent 中。",
)
async def update_user_profile(request: UserProfileUpdateRequest) -> UserProfileResponse:
    """创建或覆盖全局 USER.md。

    Args:
        request: 包含新 USER.md 内容的更新请求。

    Returns:
        包含已保存内容的 UserProfileResponse。
    """
    try:
        paths = get_paths()
        paths.base_dir.mkdir(parents=True, exist_ok=True)
        paths.user_md_file.write_text(request.content, encoding="utf-8")
        logger.info(f"Updated USER.md at {paths.user_md_file}")
        return UserProfileResponse(content=request.content or None)
    except Exception as e:
        logger.error(f"Failed to update user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新用户画像失败: {str(e)}")


@router.delete(
    "/agents/{name}",
    status_code=204,
    summary="删除自定义 Agent",
    description="删除自定义 Agent 及其所有文件 (config, SOUL.md, memory)。",
)
async def delete_agent(name: str) -> None:
    """删除一个自定义 Agent。

    Args:
        name: Agent 名称。

    Raises:
        HTTPException: 如果找不到 Agent，返回 404 错误。
    """
    _validate_agent_name(name)
    name = _normalize_agent_name(name)

    agent_dir = get_paths().agent_dir(name)

    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"未找到 Agent '{name}'")

    try:
        shutil.rmtree(agent_dir)
        logger.info(f"Deleted agent '{name}' from {agent_dir}")
    except Exception as e:
        logger.error(f"Failed to delete agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除 Agent 失败: {str(e)}")
