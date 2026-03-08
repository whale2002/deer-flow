"""技能路由器。"""

import json
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from src.gateway.path_utils import resolve_thread_virtual_path
from src.skills import Skill, load_skills
from src.skills.loader import get_skills_root_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["skills"])


class SkillResponse(BaseModel):
    """技能信息的响应模型。"""

    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能功能描述")
    license: str | None = Field(None, description="许可信息")
    category: str = Field(..., description="技能类别（public 或 custom）")
    enabled: bool = Field(default=True, description="此技能是否已启用")


class SkillsListResponse(BaseModel):
    """列出所有技能的响应模型。"""

    skills: list[SkillResponse]


class SkillUpdateRequest(BaseModel):
    """更新技能的请求模型。"""

    enabled: bool = Field(..., description="是否启用或禁用该技能")


class SkillInstallRequest(BaseModel):
    """从 .skill 文件安装技能的请求模型。"""

    thread_id: str = Field(..., description="所在的线程 ID")
    path: str = Field(..., description=".skill 文件的虚拟路径（例如 mnt/user-data/outputs/my-skill.skill）")


class SkillInstallResponse(BaseModel):
    """技能安装的响应模型。"""

    success: bool = Field(..., description="安装是否成功")
    skill_name: str = Field(..., description="已安装的技能名称")
    message: str = Field(..., description="安装结果消息")


# SKILL.md frontmatter 中允许的属性
ALLOWED_FRONTMATTER_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata"}


def _validate_skill_frontmatter(skill_dir: Path) -> tuple[bool, str, str | None]:
    """验证技能目录中的 SKILL.md frontmatter。

    Args:
        skill_dir: 包含 SKILL.md 的技能目录路径。

    Returns:
        包含 (is_valid, message, skill_name) 的元组。
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return False, "未找到 SKILL.md", None

    content = skill_md.read_text()
    if not content.startswith("---"):
        return False, "未找到 YAML frontmatter", None

    # 提取 frontmatter
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "无效的 frontmatter 格式", None

    frontmatter_text = match.group(1)

    # 解析 YAML frontmatter
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter 必须是 YAML 字典", None
    except yaml.YAMLError as e:
        return False, f"Frontmatter 中存在无效的 YAML: {e}", None

    # 检查意外属性
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_FRONTMATTER_PROPERTIES
    if unexpected_keys:
        return False, f"SKILL.md frontmatter 中存在意外的键: {', '.join(sorted(unexpected_keys))}", None

    # 检查必需字段
    if "name" not in frontmatter:
        return False, "frontmatter 中缺少 'name'", None
    if "description" not in frontmatter:
        return False, "frontmatter 中缺少 'description'", None

    # 验证名称
    name = frontmatter.get("name", "")
    if not isinstance(name, str):
        return False, f"名称必须是字符串，得到的是 {type(name).__name__}", None
    name = name.strip()
    if not name:
        return False, "名称不能为空", None

    # 检查命名约定（连字符命名法：仅小写字母、数字和连字符）
    if not re.match(r"^[a-z0-9-]+$", name):
        return False, f"名称 '{name}' 应为连字符命名法（仅小写字母、数字和连字符）", None
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False, f"名称 '{name}' 不能以连字符开头/结尾或包含连续连字符", None
    if len(name) > 64:
        return False, f"名称太长（{len(name)} 个字符）。最大为 64 个字符。", None

    # 验证描述
    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        return False, f"描述必须是字符串，得到的是 {type(description).__name__}", None
    description = description.strip()
    if description:
        if "<" in description or ">" in description:
            return False, "描述不能包含尖括号（< 或 >）", None
        if len(description) > 1024:
            return False, f"描述太长（{len(description)} 个字符）。最大为 1024 个字符。", None

    return True, "技能有效！", name


def _skill_to_response(skill: Skill) -> SkillResponse:
    """将 Skill 对象转换为 SkillResponse。"""
    return SkillResponse(
        name=skill.name,
        description=skill.description,
        license=skill.license,
        category=skill.category,
        enabled=skill.enabled,
    )


@router.get(
    "/skills",
    response_model=SkillsListResponse,
    summary="列出所有技能",
    description="检索所有可用技能的列表（包括 public 和 custom 目录）。",
)
async def list_skills() -> SkillsListResponse:
    """列出所有可用技能。

    无论启用状态如何，都返回所有技能。

    Returns:
        包含元数据的所有技能列表。

    Example Response:
        ```json
        {
            "skills": [
                {
                    "name": "PDF Processing",
                    "description": "Extract and analyze PDF content",
                    "license": "MIT",
                    "category": "public",
                    "enabled": true
                },
                {
                    "name": "Frontend Design",
                    "description": "Generate frontend designs and components",
                    "license": null,
                    "category": "custom",
                    "enabled": false
                }
            ]
        }
        ```
    """
    try:
        # 加载所有技能（包括禁用的）
        skills = load_skills(enabled_only=False)
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error(f"Failed to load skills: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load skills: {str(e)}")


@router.get(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="获取技能详情",
    description="通过名称检索特定技能的详细信息。",
)
async def get_skill(skill_name: str) -> SkillResponse:
    """按名称获取特定技能。

    Args:
        skill_name: 要检索的技能名称。

    Returns:
        如果找到则返回技能信息。

    Raises:
        HTTPException: 如果未找到技能则返回 404。

    Example Response:
        ```json
        {
            "name": "PDF Processing",
            "description": "Extract and analyze PDF content",
            "license": "MIT",
            "category": "public",
            "enabled": true
        }
        ```
    """
    try:
        skills = load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        return _skill_to_response(skill)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get skill: {str(e)}")


@router.put(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="更新技能",
    description="通过修改 skills_state_config.json 文件来更新技能的启用状态。",
)
async def update_skill(skill_name: str, request: SkillUpdateRequest) -> SkillResponse:
    """更新技能的启用状态。

    这将修改 skills_state_config.json 文件以更新启用状态。
    SKILL.md 文件本身不会被修改。

    Args:
        skill_name: 要更新的技能名称。
        request: 包含新启用状态的更新请求。

    Returns:
        更新后的技能信息。

    Raises:
        HTTPException: 如果未找到技能则返回 404，如果更新失败则返回 500。

    Example Request:
        ```json
        {
            "enabled": false
        }
        ```

    Example Response:
        ```json
        {
            "name": "PDF Processing",
            "description": "Extract and analyze PDF content",
            "license": "MIT",
            "category": "public",
            "enabled": false
        }
        ```
    """
    try:
        # 查找技能以验证其是否存在
        skills = load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        # 获取或创建配置路径
        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            # 在父目录（项目根目录）中创建新配置文件
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

        # 加载当前配置
        extensions_config = get_extensions_config()

        # 更新技能的启用状态
        extensions_config.skills[skill_name] = SkillStateConfig(enabled=request.enabled)

        # 转换为 JSON 格式（保留 MCP 服务器配置）
        config_data = {
            "mcpServers": {name: server.model_dump() for name, server in extensions_config.mcp_servers.items()},
            "skills": {name: {"enabled": skill_config.enabled} for name, skill_config in extensions_config.skills.items()},
        }

        # 将配置写入文件
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"Skills configuration updated and saved to: {config_path}")

        # 重新加载扩展配置以更新全局缓存
        reload_extensions_config()

        # 重新加载技能以获取更新后的状态（用于 API 响应）
        skills = load_skills(enabled_only=False)
        updated_skill = next((s for s in skills if s.name == skill_name), None)

        if updated_skill is None:
            raise HTTPException(status_code=500, detail=f"Failed to reload skill '{skill_name}' after update")

        logger.info(f"Skill '{skill_name}' enabled status updated to {request.enabled}")
        return _skill_to_response(updated_skill)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update skill: {str(e)}")


@router.post(
    "/skills/install",
    response_model=SkillInstallResponse,
    summary="安装技能",
    description="从位于线程 user-data 目录中的 .skill 文件（ZIP 归档）安装技能。",
)
async def install_skill(request: SkillInstallRequest) -> SkillInstallResponse:
    """从 .skill 文件安装技能。

    .skill 文件是一个 ZIP 归档，包含一个带有 SKILL.md 的技能目录，
    以及可选的资源（脚本、引用、资产）。

    Args:
        request: 包含 thread_id 和 .skill 文件虚拟路径的安装请求。

    Returns:
        包含技能名称和状态消息的安装结果。

    Raises:
        HTTPException:
            - 400 如果路径无效或文件不是有效的 .skill 文件
            - 403 如果访问被拒绝（检测到路径遍历）
            - 404 如果文件未找到
            - 409 如果技能已存在
            - 500 如果安装失败

    Example Request:
        ```json
        {
            "thread_id": "abc123-def456",
            "path": "/mnt/user-data/outputs/my-skill.skill"
        }
        ```

    Example Response:
        ```json
        {
            "success": true,
            "skill_name": "my-skill",
            "message": "Skill 'my-skill' installed successfully"
        }
        ```
    """
    try:
        # 将虚拟路径解析为实际文件路径
        skill_file_path = resolve_thread_virtual_path(request.thread_id, request.path)

        # 检查文件是否存在
        if not skill_file_path.exists():
            raise HTTPException(status_code=404, detail=f"Skill file not found: {request.path}")

        # 检查是否为文件
        if not skill_file_path.is_file():
            raise HTTPException(status_code=400, detail=f"Path is not a file: {request.path}")

        # 检查文件扩展名
        if not skill_file_path.suffix == ".skill":
            raise HTTPException(status_code=400, detail="File must have .skill extension")

        # 验证是否为有效的 ZIP 文件
        if not zipfile.is_zipfile(skill_file_path):
            raise HTTPException(status_code=400, detail="File is not a valid ZIP archive")

        # 获取自定义技能目录
        skills_root = get_skills_root_path()
        custom_skills_dir = skills_root / "custom"

        # 如果不存在则创建自定义目录
        custom_skills_dir.mkdir(parents=True, exist_ok=True)

        # 先解压到临时目录进行验证
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # 解压 .skill 文件
            with zipfile.ZipFile(skill_file_path, "r") as zip_ref:
                zip_ref.extractall(temp_path)

            # 查找技能目录（应该是唯一的顶级目录）
            extracted_items = list(temp_path.iterdir())
            if len(extracted_items) == 0:
                raise HTTPException(status_code=400, detail="Skill archive is empty")

            # 处理两种情况：单个目录或文件直接在根目录
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                skill_dir = extracted_items[0]
            else:
                # 文件直接在归档根目录
                skill_dir = temp_path

            # 验证技能
            is_valid, message, skill_name = _validate_skill_frontmatter(skill_dir)
            if not is_valid:
                raise HTTPException(status_code=400, detail=f"Invalid skill: {message}")

            if not skill_name:
                raise HTTPException(status_code=400, detail="Could not determine skill name")

            # 检查技能是否已存在
            target_dir = custom_skills_dir / skill_name
            if target_dir.exists():
                raise HTTPException(status_code=409, detail=f"Skill '{skill_name}' already exists. Please remove it first or use a different name.")

            # 将技能目录移动到自定义技能目录
            shutil.copytree(skill_dir, target_dir)

        logger.info(f"Skill '{skill_name}' installed successfully to {target_dir}")
        return SkillInstallResponse(success=True, skill_name=skill_name, message=f"Skill '{skill_name}' installed successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to install skill: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to install skill: {str(e)}")