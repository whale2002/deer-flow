"""MCP 服务器和技能的统一扩展配置。"""

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpOAuthConfig(BaseModel):
    """MCP 服务器的 OAuth 配置（HTTP/SSE 传输）。"""

    enabled: bool = Field(default=True, description="是否启用 OAuth 令牌注入")
    token_url: str = Field(description="OAuth 令牌端点 URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(
        default="client_credentials",
        description="OAuth 授权类型",
    )
    client_id: str | None = Field(default=None, description="OAuth 客户端 ID")
    client_secret: str | None = Field(default=None, description="OAuth 客户端密钥")
    refresh_token: str | None = Field(default=None, description="OAuth 刷新令牌（用于 refresh_token 授权类型）")
    scope: str | None = Field(default=None, description="OAuth 作用域")
    audience: str | None = Field(default=None, description="OAuth 受众（特定于提供商）")
    token_field: str = Field(default="access_token", description="令牌响应中包含访问令牌的字段名称")
    token_type_field: str = Field(default="token_type", description="令牌响应中包含令牌类型的字段名称")
    expires_in_field: str = Field(default="expires_in", description="令牌响应中包含过期时间（秒）的字段名称")
    default_token_type: str = Field(default="Bearer", description="令牌响应中缺失时使用的默认令牌类型")
    refresh_skew_seconds: int = Field(default=60, description="在过期前多少秒刷新令牌")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="发送到令牌端点的额外表单参数")
    model_config = ConfigDict(extra="allow")


class McpServerConfig(BaseModel):
    """单个 MCP 服务器的配置。"""

    enabled: bool = Field(default=True, description="是否启用此 MCP 服务器")
    type: str = Field(default="stdio", description="传输类型：'stdio'、'sse' 或 'http'")
    command: str | None = Field(default=None, description="启动 MCP 服务器的命令（用于 stdio 类型）")
    args: list[str] = Field(default_factory=list, description="传递给命令的参数（用于 stdio 类型）")
    env: dict[str, str] = Field(default_factory=dict, description="MCP 服务器的环境变量")
    url: str | None = Field(default=None, description="MCP 服务器的 URL（用于 sse 或 http 类型）")
    headers: dict[str, str] = Field(default_factory=dict, description="发送的 HTTP 头（用于 sse 或 http 类型）")
    oauth: McpOAuthConfig | None = Field(default=None, description="OAuth 配置（用于 sse 或 http 类型）")
    description: str = Field(default="", description="关于此 MCP 服务器提供的功能的人类可读描述")
    model_config = ConfigDict(extra="allow")


class SkillStateConfig(BaseModel):
    """单个技能状态的配置。"""

    enabled: bool = Field(default=True, description="是否启用此技能")


class ExtensionsConfig(BaseModel):
    """MCP 服务器和技能的统一配置。"""

    mcp_servers: dict[str, McpServerConfig] = Field(
        default_factory=dict,
        description="MCP 服务器名称到配置的映射",
        alias="mcpServers",
    )
    skills: dict[str, SkillStateConfig] = Field(
        default_factory=dict,
        description="技能名称到状态配置的映射",
    )
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """解析扩展配置文件的路径。

        优先级：
        1. 如果提供了 `config_path` 参数，则使用它。
        2. 如果提供了 `DEER_FLOW_EXTENSIONS_CONFIG_PATH` 环境变量，则使用它。
        3. 否则，在当前目录中查找 `extensions_config.json`，然后在父目录中查找。
        4. 为了向后兼容，如果找不到 `extensions_config.json`，也会检查 `mcp_config.json`。
        5. 如果都找不到，返回 None（扩展是可选的）。

        Args:
            config_path: 可选的扩展配置文件路径。

        Returns:
            如果找到则返回扩展配置文件的路径，否则返回 None。
        """
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH"))
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by environment variable `DEER_FLOW_EXTENSIONS_CONFIG_PATH` not found at {path}")
            return path
        else:
            # 检查 extensions_config.json 是否在当前目录中
            path = Path(os.getcwd()) / "extensions_config.json"
            if path.exists():
                return path

            # 检查 extensions_config.json 是否在当前工作目录的父目录中
            path = Path(os.getcwd()).parent / "extensions_config.json"
            if path.exists():
                return path

            # 向后兼容：检查 mcp_config.json
            path = Path(os.getcwd()) / "mcp_config.json"
            if path.exists():
                return path

            path = Path(os.getcwd()).parent / "mcp_config.json"
            if path.exists():
                return path

            # 扩展是可选的，如果未找到则返回 None
            return None

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "ExtensionsConfig":
        """从 JSON 文件加载扩展配置。

        详情请参阅 `resolve_config_path`。

        Args:
            config_path: 扩展配置文件的路径。

        Returns:
            ExtensionsConfig: 加载的配置，如果文件未找到则为空配置。
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            # 如果未找到扩展配置文件，则返回空配置
            return cls(mcp_servers={}, skills={})

        with open(resolved_path, encoding="utf-8") as f:
            config_data = json.load(f)

        cls.resolve_env_variables(config_data)
        return cls.model_validate(config_data)

    @classmethod
    def resolve_env_variables(cls, config: dict[str, Any]) -> dict[str, Any]:
        """递归解析配置中的环境变量。

        使用 `os.getenv` 函数解析环境变量。示例：$OPENAI_API_KEY

        Args:
            config: 要解析环境变量的配置。

        Returns:
            已解析环境变量的配置。
        """
        for key, value in config.items():
            if isinstance(value, str):
                if value.startswith("$"):
                    env_value = os.getenv(value[1:])
                    if env_value is None:
                        raise ValueError(f"Environment variable {value[1:]} not found for config value {value}")
                    config[key] = env_value
                else:
                    config[key] = value
            elif isinstance(value, dict):
                config[key] = cls.resolve_env_variables(value)
            elif isinstance(value, list):
                config[key] = [cls.resolve_env_variables(item) if isinstance(item, dict) else item for item in value]
        return config

    def get_enabled_mcp_servers(self) -> dict[str, McpServerConfig]:
        """仅获取已启用的 MCP 服务器。

        Returns:
            已启用 MCP 服务器的字典。
        """
        return {name: config for name, config in self.mcp_servers.items() if config.enabled}

    def is_skill_enabled(self, skill_name: str, skill_category: str) -> bool:
        """检查技能是否已启用。

        Args:
            skill_name: 技能名称
            skill_category: 技能类别

        Returns:
            如果已启用则返回 True，否则返回 False
        """
        skill_config = self.skills.get(skill_name)
        if skill_config is None:
            # 默认启用 public 和 custom 技能
            return skill_category in ("public", "custom")
        return skill_config.enabled


_extensions_config: ExtensionsConfig | None = None


def get_extensions_config() -> ExtensionsConfig:
    """获取扩展配置实例。

    返回缓存的单例实例。使用 `reload_extensions_config()` 从文件重新加载，
    或使用 `reset_extensions_config()` 清除缓存。

    Returns:
        缓存的 ExtensionsConfig 实例。
    """
    global _extensions_config
    if _extensions_config is None:
        _extensions_config = ExtensionsConfig.from_file()
    return _extensions_config


def reload_extensions_config(config_path: str | None = None) -> ExtensionsConfig:
    """从文件重新加载扩展配置并更新缓存的实例。

    这在配置文件已被修改且您希望在不重新启动应用程序的情况下获取更改时非常有用。

    Args:
        config_path: 可选的扩展配置文件路径。如果未提供，则使用默认解析策略。

    Returns:
        新加载的 ExtensionsConfig 实例。
    """
    global _extensions_config
    _extensions_config = ExtensionsConfig.from_file(config_path)
    return _extensions_config


def reset_extensions_config() -> None:
    """重置缓存的扩展配置实例。

    这将清除单例缓存，导致下次调用 `get_extensions_config()` 时从文件重新加载。
    这对于测试或在不同配置之间切换时非常有用。
    """
    global _extensions_config
    _extensions_config = None


def set_extensions_config(config: ExtensionsConfig) -> None:
    """设置自定义扩展配置实例。

    这允许为测试目的注入自定义或模拟配置。

    Args:
        config: 要使用的 ExtensionsConfig 实例。
    """
    global _extensions_config
    _extensions_config = config
