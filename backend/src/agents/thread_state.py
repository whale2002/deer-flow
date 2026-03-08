from typing import Annotated, NotRequired, TypedDict

from langchain.agents import AgentState


class SandboxState(TypedDict):
    """沙箱状态定义。"""

    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    """线程数据状态定义（包含工作区、上传和输出路径）。"""

    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    """已查看图片的数据结构。"""

    base64: str
    mime_type: str


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """产物列表的归约函数 (Reducer) - 合并并去重产物。"""
    if existing is None:
        return new or []
    if new is None:
        return existing
    # 使用 dict.fromkeys 进行去重，同时保持顺序
    return list(dict.fromkeys(existing + new))


def merge_viewed_images(existing: dict[str, ViewedImageData] | None, new: dict[str, ViewedImageData] | None) -> dict[str, ViewedImageData]:
    """viewed_images 字典的归约函数 (Reducer) - 合并图片字典。

    特殊情况：如果 new 是空字典 {}，则清空现有的图片。
    这允许中间件在处理后清除 viewed_images 状态。
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing
    # 特殊情况：空字典意味着清除所有已查看的图片
    if len(new) == 0:
        return {}
    # 合并字典，对于相同的键，新值覆盖旧值
    return {**existing, **new}


class ThreadState(AgentState):
    """线程状态定义 (AgentState)。"""

    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    todos: NotRequired[list | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> {base64, mime_type}
