"""对话摘要配置。"""

from typing import Literal

from pydantic import BaseModel, Field

ContextSizeType = Literal["fraction", "tokens", "messages"]


class ContextSize(BaseModel):
    """用于触发或保留参数的上下文大小规范。"""

    type: ContextSizeType = Field(description="上下文大小规范的类型")
    value: int | float = Field(description="上下文大小规范的值")

    def to_tuple(self) -> tuple[ContextSizeType, int | float]:
        """转换为 SummarizationMiddleware 期望的元组格式。"""
        return (self.type, self.value)


class SummarizationConfig(BaseModel):
    """自动对话摘要配置。"""

    enabled: bool = Field(
        default=False,
        description="是否启用自动对话摘要",
    )
    model_name: str | None = Field(
        default=None,
        description="用于摘要的模型名称（None = 使用轻量级模型）",
    )
    trigger: ContextSize | list[ContextSize] | None = Field(
        default=None,
        description="触发摘要的一个或多个阈值。当满足任何阈值时，运行摘要。"
        "示例：{'type': 'messages', 'value': 50} 在 50 条消息时触发，"
        "{'type': 'tokens', 'value': 4000} 在 4000 个 Token 时触发，"
        "{'type': 'fraction', 'value': 0.8} 在模型最大输入 Token 的 80% 时触发",
    )
    keep: ContextSize = Field(
        default_factory=lambda: ContextSize(type="messages", value=20),
        description="摘要后的上下文保留策略。指定要保留多少历史记录。"
        "示例：{'type': 'messages', 'value': 20} 保留 20 条消息，"
        "{'type': 'tokens', 'value': 3000} 保留 3000 个 Token，"
        "{'type': 'fraction', 'value': 0.3} 保留模型最大输入 Token 的 30%",
    )
    trim_tokens_to_summarize: int | None = Field(
        default=4000,
        description="准备用于摘要的消息时保留的最大 Token 数。传递 null 以跳过修剪。",
    )
    summary_prompt: str | None = Field(
        default=None,
        description="生成摘要的自定义提示词模板。如果未提供，则使用默认的 LangChain 提示词。",
    )


# 全局配置实例
_summarization_config: SummarizationConfig = SummarizationConfig()


def get_summarization_config() -> SummarizationConfig:
    """获取当前摘要配置。"""
    return _summarization_config


def set_summarization_config(config: SummarizationConfig) -> None:
    """设置摘要配置。"""
    global _summarization_config
    _summarization_config = config


def load_summarization_config_from_dict(config_dict: dict) -> None:
    """从字典加载摘要配置。"""
    global _summarization_config
    _summarization_config = SummarizationConfig(**config_dict)
