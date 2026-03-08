"""用于线程虚拟路径（例如 mnt/user-data/outputs/...）的共享路径解析。"""

from pathlib import Path

from fastapi import HTTPException

from src.config.paths import get_paths


def resolve_thread_virtual_path(thread_id: str, virtual_path: str) -> Path:
    """将虚拟路径解析为线程 user-data 下的实际文件系统路径。

    Args:
        thread_id: 线程 ID。
        virtual_path: 沙箱内部看到的虚拟路径
                      （例如 /mnt/user-data/outputs/file.txt）。

    Returns:
        解析后的文件系统路径。

    Raises:
        HTTPException: 如果路径无效或在允许的目录之外。
    """
    try:
        return get_paths().resolve_virtual_path(thread_id, virtual_path)
    except ValueError as e:
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
