from pydantic import BaseModel, ConfigDict, Field


class ModelConfig(BaseModel):
    """模型的配置部分"""

    name: str = Field(..., description="模型的唯一名称")
    display_name: str | None = Field(..., default_factory=lambda: None, description="模型的显示名称")
    description: str | None = Field(..., default_factory=lambda: None, description="模型描述")
    use: str = Field(
        ...,
        description="模型提供者的类路径（例如 langchain_openai.ChatOpenAI）",
    )
    model: str = Field(..., description="模型名称")
    model_config = ConfigDict(extra="allow")
    supports_thinking: bool = Field(default_factory=lambda: False, description="模型是否支持思考（Thinking）")
    supports_reasoning_effort: bool = Field(default_factory=lambda: False, description="模型是否支持推理力度（Reasoning Effort）")
    when_thinking_enabled: dict | None = Field(
        default_factory=lambda: None,
        description="当启用思考时传递给模型的额外设置",
    )
    supports_vision: bool = Field(default_factory=lambda: False, description="模型是否支持视觉/图像输入")
    thinking: dict | None = Field(
        default_factory=lambda: None,
        description=(
            "模型的思考设置。如果提供，这些设置将在启用思考时传递给模型。"
            "这是 `when_thinking_enabled` 的快捷方式，如果两者都提供，将与 `when_thinking_enabled` 合并。"
        ),
    )
