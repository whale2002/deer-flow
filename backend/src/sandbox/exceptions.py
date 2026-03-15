"""沙箱相关的异常类，带有结构化的错误信息。"""


class SandboxError(Exception):
    """所有沙箱相关异常的基类。"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({detail_str})"
        return self.message


class SandboxNotFoundError(SandboxError):
    """当沙箱找不到或不可用时抛出。"""

    def __init__(self, message: str = "沙箱未找到", sandbox_id: str | None = None):
        details = {"sandbox_id": sandbox_id} if sandbox_id else None
        super().__init__(message, details)
        self.sandbox_id = sandbox_id


class SandboxRuntimeError(SandboxError):
    """当沙箱运行时不可用或配置错误时抛出。"""

    pass


class SandboxCommandError(SandboxError):
    """当沙箱中的命令执行失败时抛出。"""

    def __init__(self, message: str, command: str | None = None, exit_code: int | None = None):
        details = {}
        if command:
            details["command"] = command[:100] + "..." if len(command) > 100 else command
        if exit_code is not None:
            details["exit_code"] = exit_code
        super().__init__(message, details)
        self.command = command
        self.exit_code = exit_code


class SandboxFileError(SandboxError):
    """当沙箱中的文件操作失败时抛出。"""

    def __init__(self, message: str, path: str | None = None, operation: str | None = None):
        details = {}
        if path:
            details["path"] = path
        if operation:
            details["operation"] = operation
        super().__init__(message, details)
        self.path = path
        self.operation = operation


class SandboxPermissionError(SandboxFileError):
    """当文件操作过程中发生权限错误时抛出。"""

    pass


class SandboxFileNotFoundError(SandboxFileError):
    """当文件或目录未找到时抛出。"""

    pass
