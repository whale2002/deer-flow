"""列出目录内容的工具函数。"""

import fnmatch
from pathlib import Path

IGNORE_PATTERNS = [
    # Version Control
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    # Dependencies
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    "env",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "site-packages",
    # Build outputs
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".output",
    ".turbo",
    "target",
    "out",
    # IDE & Editor
    ".idea",
    ".vscode",
    "*.swp",
    "*.swo",
    "*~",
    ".project",
    ".classpath",
    ".settings",
    # OS generated
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "*.lnk",
    # Logs & temp files
    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",
    "*.cache",
    ".cache",
    "logs",
    # Coverage & test artifacts
    ".coverage",
    "coverage",
    ".nyc_output",
    "htmlcov",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]


def _should_ignore(name: str) -> bool:
    """检查文件名/目录名是否匹配任何忽略模式。"""
    for pattern in IGNORE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def list_dir(path: str, max_depth: int = 2, _current_depth: int = 0, _base_path: str | None = None) -> list[str]:
    """列出目录内容，最深为指定深度。

    返回目录树结构的字符串表示，每行缩进表示深度。

    Args:
        path: 目录的绝对路径。
        max_depth: 最大遍历深度（默认 2）。
        _current_depth: 内部参数，用于跟踪当前递归深度。
        _base_path: 内部参数，用于跟踪遍历的基准路径。

    Returns:
        目录内容的列表，每行表示一个文件或目录，带有适当的缩进。
    """
    if _current_depth == 0:
        _base_path = str(Path(path).resolve())

    path_obj = Path(path)
    result = []

    if not path_obj.exists():
        raise FileNotFoundError(f"路径不存在: {path}")
    if not path_obj.is_dir():
        raise NotADirectoryError(f"路径不是目录: {path}")

    try:
        entries = sorted(path_obj.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    except PermissionError:
        return [f"{'  ' * _current_depth}[权限被拒绝]"]

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        prefix = "└── " if is_last else "├── "
        connector = "  " if is_last else "│  "

        if entry.is_dir():
            if _should_ignore(entry.name):
                continue
            result.append(f"{'  ' * _current_depth}{prefix}{entry.name}/")
            if _current_depth < max_depth:
                try:
                    sub_entries = list_dir(str(entry), max_depth, _current_depth + 1, _base_path)
                    result.extend(sub_entries)
                except PermissionError:
                    result.append(f"{'  ' * (_current_depth + 1)}[权限被拒绝]")
        else:
            if _should_ignore(entry.name):
                continue
            size = entry.stat().st_size
            size_str = format_size(size)
            result.append(f"{'  ' * _current_depth}{prefix}{entry.name} ({size_str})")

    return result


def format_size(size: int) -> str:
    """格式化文件大小为人类可读的字符串。

    Args:
        size: 以字节为单位的文件大小。

    Returns:
        格式化的字符串，如 "1.5 KB"、"2.3 MB" 等。
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"
