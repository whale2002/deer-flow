from pydantic import BaseModel, ConfigDict, Field


class ToolGroupConfig(BaseModel):
    """工具组的配置部分"""

    name: str = Field(..., description="工具组的唯一名称")
    model_config = ConfigDict(extra="allow")


class ToolConfig(BaseModel):
    """工具的配置部分"""

    name: str = Field(..., description="工具的唯一名称")
    group: str = Field(..., description="工具的组名")
    use: str = Field(
        ...,
        description="工具提供者的变量名（例如 src.sandbox.tools:bash_tool）",
    )
    model_config = ConfigDict(extra="allow")
