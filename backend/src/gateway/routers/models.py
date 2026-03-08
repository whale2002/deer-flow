"""用于模型管理的路由器。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config import get_app_config

router = APIRouter(prefix="/api", tags=["models"])


class ModelResponse(BaseModel):
    """模型信息响应模型。"""

    name: str = Field(..., description="模型的唯一标识符")
    display_name: str | None = Field(None, description="人类可读的显示名称")
    description: str | None = Field(None, description="模型描述")
    supports_thinking: bool = Field(default=False, description="模型是否支持思考模式")
    supports_reasoning_effort: bool = Field(default=False, description="模型是否支持推理力度")


class ModelsListResponse(BaseModel):
    """列出所有模型的响应模型。"""

    models: list[ModelResponse]


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="列出所有模型",
    description="获取系统中配置的所有可用 AI 模型列表。",
)
async def list_models() -> ModelsListResponse:
    """列出配置中的所有可用模型。

    返回适合前端显示的模型信息，
    排除 API 密钥和内部配置等敏感字段。

    Returns:
        所有已配置模型及其元数据的列表。

    Example Response:
        ```json
        {
            "models": [
                {
                    "name": "gpt-4",
                    "display_name": "GPT-4",
                    "description": "OpenAI GPT-4 model",
                    "supports_thinking": false
                },
                {
                    "name": "claude-3-opus",
                    "display_name": "Claude 3 Opus",
                    "description": "Anthropic Claude 3 Opus model",
                    "supports_thinking": true
                }
            ]
        }
        ```
    """
    config = get_app_config()
    models = [
        ModelResponse(
            name=model.name,
            display_name=model.display_name,
            description=model.description,
            supports_thinking=model.supports_thinking,
            supports_reasoning_effort=model.supports_reasoning_effort,
        )
        for model in config.models
    ]
    return ModelsListResponse(models=models)


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="获取模型详情",
    description="通过名称检索特定 AI 模型的详细信息。",
)
async def get_model(model_name: str) -> ModelResponse:
    """按名称获取特定模型。

    Args:
        model_name: 要检索的模型的唯一名称。

    Returns:
        如果找到则返回模型信息。

    Raises:
        HTTPException: 如果未找到模型则返回 404。

    Example Response:
        ```json
        {
            "name": "gpt-4",
            "display_name": "GPT-4",
            "description": "OpenAI GPT-4 model",
            "supports_thinking": false
        }
        ```
    """
    config = get_app_config()
    model = config.get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return ModelResponse(
        name=model.name,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
    )
