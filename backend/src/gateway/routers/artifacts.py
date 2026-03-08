import logging
import mimetypes
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from src.gateway.path_utils import resolve_thread_virtual_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["artifacts"])


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """通过检查内容是否包含空字节来判断文件是否为文本文件。"""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            # 文本文件通常不包含空字节
            return b"\x00" not in chunk
    except Exception:
        return False


def _extract_file_from_skill_archive(zip_path: Path, internal_path: str) -> bytes | None:
    """从 .skill ZIP 归档文件中提取文件。

    Args:
        zip_path: .skill 文件 (ZIP 归档) 的路径。
        internal_path: 归档内的文件路径 (例如 "SKILL.md")。

    Returns:
        文件内容的字节流，如果未找到则返回 None。
    """
    if not zipfile.is_zipfile(zip_path):
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # 列出归档中的所有文件
            namelist = zip_ref.namelist()

            # 首先尝试直接匹配路径
            if internal_path in namelist:
                return zip_ref.read(internal_path)

            # 尝试匹配带任意顶级目录前缀的路径 (例如 "skill-name/SKILL.md")
            for name in namelist:
                if name.endswith("/" + internal_path) or name == internal_path:
                    return zip_ref.read(name)

            # 未找到
            return None
    except (zipfile.BadZipFile, KeyError):
        return None


@router.get(
    "/threads/{thread_id}/artifacts/{path:path}",
    summary="获取产物文件 (Artifact)",
    description="检索 AI Agent 生成的产物文件。支持文本、HTML 和二进制文件。",
)
async def get_artifact(thread_id: str, path: str, request: Request) -> FileResponse:
    """根据路径获取产物文件。

    该端点会自动检测文件类型并返回相应的 Content-Type。
    使用 `?download=true` 查询参数可强制下载文件。

    Args:
        thread_id: 线程 ID。
        path: 带有虚拟前缀的产物路径 (例如 mnt/user-data/outputs/file.txt)。
        request: FastAPI 请求对象 (自动注入)。

    Returns:
        带有适当 Content-Type 的 FileResponse 文件内容：
        - HTML 文件：渲染为 HTML 页面
        - 文本文件：带有正确 MIME 类型的纯文本
        - 二进制文件：内联显示 (inline) 或下载

    Raises:
        HTTPException:
            - 400: 路径无效或不是文件
            - 403: 拒绝访问 (检测到路径遍历攻击)
            - 404: 文件未找到

    Query Parameters:
        download (bool): 如果为 true，则作为附件返回以供下载

    Example:
        - 获取 HTML 文件: `/api/threads/abc123/artifacts/mnt/user-data/outputs/index.html`
        - 下载文件: `/api/threads/abc123/artifacts/mnt/user-data/outputs/data.csv?download=true`
    """
    # 检查是否请求 .skill 归档中的文件 (例如 xxx.skill/SKILL.md)
    if ".skill/" in path:
        # 在 ".skill/" 处分割路径以获取 ZIP 文件路径和内部路径
        skill_marker = ".skill/"
        marker_pos = path.find(skill_marker)
        skill_file_path = path[: marker_pos + len(".skill")]  # 例如 "mnt/user-data/outputs/my-skill.skill"
        internal_path = path[marker_pos + len(skill_marker) :]  # 例如 "SKILL.md"

        actual_skill_path = resolve_thread_virtual_path(thread_id, skill_file_path)

        if not actual_skill_path.exists():
            raise HTTPException(status_code=404, detail=f"Skill 文件未找到: {skill_file_path}")

        if not actual_skill_path.is_file():
            raise HTTPException(status_code=400, detail=f"路径不是一个文件: {skill_file_path}")

        # 从 .skill 归档中提取文件
        content = _extract_file_from_skill_archive(actual_skill_path, internal_path)
        if content is None:
            raise HTTPException(status_code=404, detail=f"在 skill 归档中未找到文件 '{internal_path}'")

        # 根据内部文件确定 MIME 类型
        mime_type, _ = mimetypes.guess_type(internal_path)
        # 添加缓存头以避免重复解压 (缓存 5 分钟)
        cache_headers = {"Cache-Control": "private, max-age=300"}
        if mime_type and mime_type.startswith("text/"):
            return PlainTextResponse(content=content.decode("utf-8"), media_type=mime_type, headers=cache_headers)

        # 对于看起来像文本的未知类型，默认为纯文本
        try:
            return PlainTextResponse(content=content.decode("utf-8"), media_type="text/plain", headers=cache_headers)
        except UnicodeDecodeError:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=cache_headers)

    # 解析常规文件路径
    actual_path = resolve_thread_virtual_path(thread_id, path)

    logger.info(f"Resolving artifact path: thread_id={thread_id}, requested_path={path}, actual_path={actual_path}")

    if not actual_path.exists():
        raise HTTPException(status_code=404, detail=f"产物未找到: {path}")

    if not actual_path.is_file():
        raise HTTPException(status_code=400, detail=f"路径不是一个文件: {path}")

    mime_type, _ = mimetypes.guess_type(actual_path)

    # 对文件名进行编码以用于 Content-Disposition 标头 (RFC 5987)
    encoded_filename = quote(actual_path.name)

    # 如果 `download` 查询参数为 true，则将文件作为附件下载返回
    if request.query_params.get("download"):
        return FileResponse(
            path=actual_path,
            filename=actual_path.name,
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
        )

    # 如果是 HTML，则直接渲染
    if mime_type and mime_type == "text/html":
        return HTMLResponse(content=actual_path.read_text())

    # 如果是文本文件，则以纯文本返回
    if mime_type and mime_type.startswith("text/"):
        return PlainTextResponse(content=actual_path.read_text(), media_type=mime_type)

    # 通过内容检测是否为文本文件
    if is_text_file_by_content(actual_path):
        return PlainTextResponse(content=actual_path.read_text(), media_type=mime_type)

    # 二进制文件：内联显示 (inline)
    return Response(
        content=actual_path.read_bytes(),
        media_type=mime_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"},
    )
