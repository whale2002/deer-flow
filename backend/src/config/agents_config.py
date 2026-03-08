"""自定义 Agent 的配置和加载器。"""

import logging
import re
from typing import Any

import yaml
from pydantic import BaseModel

from src.config.paths import get_paths

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentConfig(BaseModel):
    """自定义 Agent 的配置。"""

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None


def load_agent_config(name: str | None) -> AgentConfig | None:
    """从目录加载自定义或默认 Agent 的配置。

    Args:
        name: Agent 名称。

    Returns:
        AgentConfig 实例。

    Raises:
        FileNotFoundError: 如果 Agent 目录或 config.yaml 不存在。
        ValueError: 如果 config.yaml 无法解析。
    """

    if name is None:
        return None

    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    agent_dir = get_paths().agent_dir(name)
    config_file = agent_dir / "config.yaml"

    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    if not config_file.exists():
        raise FileNotFoundError(f"Agent config not found: {config_file}")

    try:
        with open(config_file, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse agent config {config_file}: {e}") from e

    # 如果文件中没有 name，确保从目录名设置 name
    if "name" not in data:
        data["name"] = name

    # 在传递给 Pydantic 之前剥离未知字段（例如旧版 prompt_file）
    known_fields = set(AgentConfig.model_fields.keys())
    data = {k: v for k, v in data.items() if k in known_fields}

    return AgentConfig(**data)


def load_agent_soul(agent_name: str | None) -> str | None:
    """读取自定义 Agent 的 SOUL.md 文件（如果存在）。

    SOUL.md 定义了 Agent 的个性、价值观和行为准则。
    它被作为附加上下文注入到 Lead Agent 的系统提示词中。

    Args:
        agent_name: Agent 名称，None 表示默认 Agent。

    Returns:
        SOUL.md 内容字符串，如果文件不存在则返回 None。
    """
    agent_dir = get_paths().agent_dir(agent_name) if agent_name else get_paths().base_dir
    soul_path = agent_dir / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def list_custom_agents() -> list[AgentConfig]:
    """扫描 agents 目录并返回所有有效的自定义 Agent。

    Returns:
        每个找到的有效 Agent 目录的 AgentConfig 列表。
    """
    agents_dir = get_paths().agents_dir

    if not agents_dir.exists():
        return []

    agents: list[AgentConfig] = []

    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir():
            continue

        config_file = entry / "config.yaml"
        if not config_file.exists():
            logger.debug(f"Skipping {entry.name}: no config.yaml")
            continue

        try:
            agent_cfg = load_agent_config(entry.name)
            agents.append(agent_cfg)
        except Exception as e:
            logger.warning(f"Skipping agent '{entry.name}': {e}")

    return agents
