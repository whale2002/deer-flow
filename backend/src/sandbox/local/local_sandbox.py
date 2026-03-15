"""本地沙箱实现 - 在本地文件系统上执行命令和文件操作。"""

import os
import shutil
import subprocess
from pathlib import Path

from src.sandbox.local.list_dir import list_dir
from src.sandbox.sandbox import Sandbox


class LocalSandbox(Sandbox):
    """本地沙箱实现"""

    def __init__(self, id: str, path_mappings: dict[str, str] | None = None):
        """初始化本地沙箱，带可选的路径映射。

        Args:
            id: 沙箱标识符
            path_mappings: 容器路径到本地路径的映射字典
                          示例：{"/mnt/skills": "/absolute/path/to/skills"}
        """
        super().__init__(id)
        self.path_mappings = path_mappings or {}

    def _resolve_path(self, path: str) -> str:
        """使用映射将容器路径解析为实际本地路径。

        Args:
            path: 可能是容器路径的路径

        Returns:
            解析后的本地路径
        """
        path_str = str(path)

        # 尝试每个映射（最长前缀优先以获得更精确的匹配）
        for container_path, local_path in sorted(self.path_mappings.items(), key=lambda x: len(x[0]), reverse=True):
            if path_str.startswith(container_path):
                # 用本地路径替换容器路径前缀
                relative = path_str[len(container_path) :].lstrip("/")
                resolved = str(Path(local_path) / relative) if relative else local_path
                return resolved

        # 未找到映射，返回原始路径
        return path_str

    def _reverse_resolve_path(self, path: str) -> str:
        """使用映射将本地路径反向解析为容器路径。

        Args:
            path: 可能需要映射到容器路径的本地路径

        Returns:
            如果存在映射则返回容器路径，否则返回原始路径
        """
        path_str = str(Path(path).resolve())

        # 尝试每个映射（最长本地路径优先以获得更精确的匹配）
        for container_path, local_path in sorted(self.path_mappings.items(), key=lambda x: len(x[1]), reverse=True):
            local_path_resolved = str(Path(local_path).resolve())
            if path_str.startswith(local_path_resolved):
                # 用容器路径替换本地路径前缀
                relative = path_str[len(local_path_resolved) :].lstrip("/")
                resolved = f"{container_path}/{relative}" if relative else container_path
                return resolved

        # 未找到映射，返回原始路径
        return path_str

    def _reverse_resolve_paths_in_output(self, output: str) -> str:
        """在输出字符串中将本地路径反向解析为容器路径。

        Args:
            output: 可能包含本地路径的输出字符串

        Returns:
            本地路径解析为容器路径后的输出
        """
        import re

        # 按本地路径长度排序映射（最长优先）以正确匹配前缀
        sorted_mappings = sorted(self.path_mappings.items(), key=lambda x: len(x[1]), reverse=True)

        if not sorted_mappings:
            return output

        # 创建匹配绝对路径的模式
        # 匹配类似 /Users/... 或其他绝对路径的路径
        result = output
        for container_path, local_path in sorted_mappings:
            local_path_resolved = str(Path(local_path).resolve())
            # 转义本地路径以用于正则表达式
            escaped_local = re.escape(local_path_resolved)
            # 匹配本地路径后跟可选的路径组件
            pattern = re.compile(escaped_local + r"(?:/[^\s\"';&|<>()]*)?")

            def replace_match(match: re.Match) -> str:
                matched_path = match.group(0)
                return self._reverse_resolve_path(matched_path)

            result = pattern.sub(replace_match, result)

        return result

    def _resolve_paths_in_command(self, command: str) -> str:
        """在命令字符串中将容器路径解析为本地路径。

        Args:
            command: 可能包含容器路径的命令字符串

        Returns:
            容器路径解析为本地路径后的命令
        """
        import re

        # 按长度排序映射（最长优先）以正确匹配前缀
        sorted_mappings = sorted(self.path_mappings.items(), key=lambda x: len(x[0]), reverse=True)

        # 构建正则表达式模式以匹配所有容器路径
        # 匹配容器路径后跟可选的路径组件
        if not sorted_mappings:
            return command

        # 创建匹配任何容器路径的模式
        patterns = [re.escape(container_path) + r"(?:/[^\s\"';&|<>()]*)??" for container_path, _ in sorted_mappings]
        pattern = re.compile("|".join(f"({p})" for p in patterns))

        def replace_match(match: re.Match) -> str:
            matched_path = match.group(0)
            return self._resolve_path(matched_path)

        return pattern.sub(replace_match, command)

    @staticmethod
    def _get_shell() -> str:
        """检测可用的 shell 可执行文件，带回退。

        按优先级顺序返回第一个可用的 shell：
        /bin/zsh → /bin/bash → /bin/sh → PATH 上找到的第一个 `sh`。
        如果找不到合适的 shell 则抛出 RuntimeError。
        """
        for shell in ("/bin/zsh", "/bin/bash", "/bin/sh"):
            if os.path.isfile(shell) and os.access(shell, os.X_OK):
                return shell
        shell_from_path = shutil.which("sh")
        if shell_from_path is not None:
            return shell_from_path
        raise RuntimeError("找不到合适的 shell 可执行文件。尝试了 /bin/zsh、/bin/bash、/bin/sh 和 PATH 上的 `sh`。")

    def execute_command(self, command: str) -> str:
        """执行命令。

        Args:
            command: 要执行的命令。

        Returns:
            命令的输出。
        """
        # 执行前解析命令中的容器路径
        resolved_command = self._resolve_paths_in_command(command)

        result = subprocess.run(
            resolved_command,
            executable=self._get_shell(),
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n标准错误:\n{result.stderr}" if output else result.stderr
        if result.returncode != 0:
            output += f"\n退出码: {result.returncode}"

        final_output = output if output else "(无输出)"
        # 在输出中将本地路径反向解析为容器路径
        return self._reverse_resolve_paths_in_output(final_output)

    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """列出目录内容。

        Args:
            path: 目录路径。
            max_depth: 最大深度（默认 2）。

        Returns:
            目录中的文件和目录列表。
        """
        resolved_path = self._resolve_path(path)
        entries = list_dir(resolved_path, max_depth)
        # 在输出中将本地路径反向解析为容器路径
        return [self._reverse_resolve_paths_in_output(entry) for entry in entries]

    def read_file(self, path: str) -> str:
        """读取文件内容。

        Args:
            path: 文件路径。

        Returns:
            文件内容。
        """
        resolved_path = self._resolve_path(path)
        try:
            with open(resolved_path) as f:
                return f.read()
        except OSError as e:
            # 使用原始路径重新抛出以获得更清晰的错误消息，隐藏内部解析路径
            raise type(e)(e.errno, e.strerror, path) from None

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """写入文件内容。

        Args:
            path: 文件路径。
            content: 要写入的内容。
            append: 是否追加内容。
        """
        resolved_path = self._resolve_path(path)
        try:
            dir_path = os.path.dirname(resolved_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            mode = "a" if append else "w"
            with open(resolved_path, mode) as f:
                f.write(content)
        except OSError as e:
            # 使用原始路径重新抛出以获得更清晰的错误消息，隐藏内部解析路径
            raise type(e)(e.errno, e.strerror, path) from None

    def update_file(self, path: str, content: bytes) -> None:
        """用二进制内容更新文件。

        Args:
            path: 文件路径。
            content: 二进制内容。
        """
        resolved_path = self._resolve_path(path)
        try:
            dir_path = os.path.dirname(resolved_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(resolved_path, "wb") as f:
                f.write(content)
        except OSError as e:
            # 使用原始路径重新抛出以获得更清晰的错误消息，隐藏内部解析路径
            raise type(e)(e.errno, e.strerror, path) from None
