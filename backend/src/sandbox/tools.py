"""沙箱工具 - Agent 可调用的文件操作和命令执行工具。"""
import re

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadDataState, ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX
from src.sandbox.exceptions import (
    SandboxError,
    SandboxNotFoundError,
    SandboxRuntimeError,
)
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import get_sandbox_provider


def replace_virtual_path(path: str, thread_data: ThreadDataState | None) -> str:
    """将虚拟路径 /mnt/user-data 替换为实际的线程数据路径。

    映射关系：
        /mnt/user-data/workspace/* -> thread_data['workspace_path']/*
        /mnt/user-data/uploads/* -> thread_data['uploads_path']/*
        /mnt/user-data/outputs/* -> thread_data['outputs_path']/*

    Args:
        path: 可能包含虚拟路径前缀的路径。
        thread_data: 包含实际路径的线程数据。

    Returns:
        虚拟前缀替换为实际路径后的路径。
    """
    if not path.startswith(VIRTUAL_PATH_PREFIX):
        return path

    if thread_data is None:
        return path

    # 将虚拟子目录映射到 thread_data 的键
    path_mapping = {
        "workspace": thread_data.get("workspace_path"),
        "uploads": thread_data.get("uploads_path"),
        "outputs": thread_data.get("outputs_path"),
    }

    # 提取 /mnt/user-data/ 后的相对路径
    relative_path = path[len(VIRTUAL_PATH_PREFIX) :].lstrip("/")
    if not relative_path:
        return path

    # 找出该路径属于哪个子目录
    parts = relative_path.split("/", 1)
    subdir = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    actual_base = path_mapping.get(subdir)
    if actual_base is None:
        return path

    if rest:
        return f"{actual_base}/{rest}"
    return actual_base


def replace_virtual_paths_in_command(command: str, thread_data: ThreadDataState | None) -> str:
    """替换命令字符串中的所有虚拟路径 /mnt/user-data。

    Args:
        command: 可能包含虚拟路径的命令字符串。
        thread_data: 包含实际路径的线程数据。

    Returns:
        所有虚拟路径替换后的命令。
    """
    if VIRTUAL_PATH_PREFIX not in command:
        return command

    if thread_data is None:
        return command

    # 匹配 /mnt/user-data 后跟路径字符的模式
    pattern = re.compile(rf"{re.escape(VIRTUAL_PATH_PREFIX)}(/[^\s\"';&|<>()]*)?")

    def replace_match(match: re.Match) -> str:
        full_path = match.group(0)
        return replace_virtual_path(full_path, thread_data)

    return pattern.sub(replace_match, command)


def get_thread_data(runtime: ToolRuntime[ContextT, ThreadState] | None) -> ThreadDataState | None:
    """从运行时状态中提取 thread_data。"""
    if runtime is None:
        return None
    if runtime.state is None:
        return None
    return runtime.state.get("thread_data")


def is_local_sandbox(runtime: ToolRuntime[ContextT, ThreadState] | None) -> bool:
    """检查当前沙箱是否为本地沙箱。

    仅本地沙箱需要路径替换，因为 aio 沙箱容器内已有 /mnt/user-data 挂载。
    """
    if runtime is None:
        return False
    if runtime.state is None:
        return False
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        return False
    return sandbox_state.get("sandbox_id") == "local"


def sandbox_from_runtime(runtime: ToolRuntime[ContextT, ThreadState] | None = None) -> Sandbox:
    """从工具运行时提取沙箱实例。

    已弃用：请使用 ensure_sandbox_initialized() 以支持懒初始化。
    此函数假设沙箱已初始化，如果未初始化将抛出错误。

    Raises:
        SandboxRuntimeError: 如果运行时不可用或缺少沙箱状态。
        SandboxNotFoundError: 如果找不到给定 ID 的沙箱。
    """
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")
    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        raise SandboxRuntimeError("Sandbox state not initialized in runtime")
    sandbox_id = sandbox_state.get("sandbox_id")
    if sandbox_id is None:
        raise SandboxRuntimeError("Sandbox ID not found in state")
    sandbox = get_sandbox_provider().get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError(f"Sandbox with ID '{sandbox_id}' not found", sandbox_id=sandbox_id)
    return sandbox


def ensure_sandbox_initialized(runtime: ToolRuntime[ContextT, ThreadState] | None = None) -> Sandbox:
    """确保沙箱已初始化，必要时进行懒获取。

    首次调用时，从提供者获取沙箱并存储在运行时状态中。
    后续调用返回现有沙箱。

    线程安全由提供者的内部锁定机制保证。

    Args:
        runtime: 包含状态和上下文的工具运行时。

    Returns:
        初始化的沙箱实例。

    Raises:
        SandboxRuntimeError: 如果运行时不可用或缺少 thread_id。
        SandboxNotFoundError: 如果沙箱获取失败。
    """
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")

    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")

    # 检查沙箱是否已存在于状态中
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = get_sandbox_provider().get(sandbox_id)
            if sandbox is not None:
                return sandbox
            # 沙箱已释放，继续获取新的

    # 懒获取：获取 thread_id 并获取沙箱
    thread_id = runtime.context.get("thread_id")
    if thread_id is None:
        raise SandboxRuntimeError("Thread ID not available in runtime context")

    provider = get_sandbox_provider()
    print(f"懒获取沙箱 for thread {thread_id}")
    sandbox_id = provider.acquire(thread_id)

    # 更新运行时状态 - 这在工具调用之间持久化
    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}

    # 获取并返回沙箱
    sandbox = provider.get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError("Sandbox not found after acquisition", sandbox_id=sandbox_id)

    return sandbox


def ensure_thread_directories_exist(runtime: ToolRuntime[ContextT, ThreadState] | None) -> None:
    """确保线程数据目录（workspace, uploads, outputs）存在。

    此函数在首次使用任何沙箱工具时懒调用。
    对于本地沙箱，它会在文件系统上创建目录。
    对于其他沙箱（如 aio），目录已在容器中挂载。

    Args:
        runtime: 包含状态和上下文的工具运行时。
    """
    if runtime is None:
        return

    # 仅本地沙箱创建目录
    if not is_local_sandbox(runtime):
        return

    thread_data = get_thread_data(runtime)
    if thread_data is None:
        return

    # 检查目录是否已创建
    if runtime.state.get("thread_directories_created"):
        return

    # 创建三个目录
    import os

    for key in ["workspace_path", "uploads_path", "outputs_path"]:
        path = thread_data.get(key)
        if path:
            os.makedirs(path, exist_ok=True)

    # 标记为已创建以避免冗余操作
    runtime.state["thread_directories_created"] = True


@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """在 Linux 环境中执行 bash 命令。

    - 使用 `python` 运行 Python 代码。
    - 使用 `pip install` 安装 Python 包。

    Args:
        description: 用简短的话解释你为什么运行这个命令。始终将此参数放在第一位。
        command: 要执行的 bash 命令。文件和目录始终使用绝对路径。
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            command = replace_virtual_paths_in_command(command, thread_data)
        return sandbox.execute_command(command)
    except SandboxError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error executing command: {type(e).__name__}: {e}"


@tool("ls", parse_docstring=True)
def ls_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, path: str) -> str:
    """列出目录内容，最深 2 层，以树形格式显示。

    Args:
        description: 用简短的话解释你为什么列出这个目录。始终将此参数放在第一位。
        path: 要列出的目录的**绝对**路径。
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)
        children = sandbox.list_dir(path)
        if not children:
            return "(empty)"
        return "\n".join(children)
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: Directory not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: Unexpected error listing directory: {type(e).__name__}: {e}"


@tool("read_file", parse_docstring=True)
def read_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """读取文本文件的内容。用于查看源代码、配置文件、日志或任何基于文本的文件。

    Args:
        description: 用简短的话解释你为什么读取这个文件。始终将此参数放在第一位。
        path: 要读取的文件的**绝对**路径。
        start_line: 可选的起始行号（从 1 开始，含）。与 end_line 一起使用以读取特定范围。
        end_line: 可选的结束行号（从 1 开始，含）。与 start_line 一起使用以读取特定范围。
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)
        content = sandbox.read_file(path)
        if not content:
            return "(empty)"
        if start_line is not None and end_line is not None:
            content = "\n".join(content.splitlines()[start_line - 1 : end_line])
        return content
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {path}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {path}"
    except Exception as e:
        return f"Error: Unexpected error reading file: {type(e).__name__}: {e}"


@tool("write_file", parse_docstring=True)
def write_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    content: str,
    append: bool = False,
) -> str:
    """将文本内容写入文件。

    Args:
        description: 用简短的话解释你为什么写入这个文件。始终将此参数放在第一位。
        path: 要写入的文件的**绝对**路径。始终将此参数放在第二位。
        content: 要写入文件的内容。始终将此参数放在第三位。
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)
        sandbox.write_file(path, content, append)
        return "OK"
    except SandboxError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: Permission denied writing to file: {path}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {path}"
    except OSError as e:
        return f"Error: Failed to write file '{path}': {e}"
    except Exception as e:
        return f"Error: Unexpected error writing file: {type(e).__name__}: {e}"


@tool("str_replace", parse_docstring=True)
def str_replace_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
) -> str:
    """替换文件中的子字符串。
    如果 `replace_all` 为 False（默认），要替换的子字符串必须在文件中**恰好出现一次**。

    Args:
        description: 用简短的话解释你为什么替换这个子字符串。始终将此参数放在第一位。
        path: 要替换子字符串的文件的**绝对**路径。始终将此参数放在第二位。
        old_str: 要替换的子字符串。始终将此参数放在第三位。
        new_str: 新的子字符串。始终将此参数放在第四位。
        replace_all: 是否替换子字符串的所有出现次数。如果为 False，仅替换第一个出现的位置。默认为 False。
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)
        content = sandbox.read_file(path)
        if not content:
            return "OK"
        if old_str not in content:
            return f"Error: String to replace not found in file: {path}"
        if replace_all:
            content = content.replace(old_str, new_str)
        else:
            content = content.replace(old_str, new_str, 1)
        sandbox.write_file(path, content)
        return "OK"
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied accessing file: {path}"
    except Exception as e:
        return f"Error: Unexpected error replacing string: {type(e).__name__}: {e}"
