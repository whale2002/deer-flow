"""沙箱环境的抽象基类定义。"""

from abc import ABC, abstractmethod


class Sandbox(ABC):
    """沙箱环境的抽象基类"""

    _id: str

    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    @abstractmethod
    def execute_command(self, command: str) -> str:
        """在沙箱中执行 bash 命令。

        Args:
            command: 要执行的命令。

        Returns:
            命令的标准输出或错误输出。
        """
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取文件内容。

        Args:
            path: 要读取的文件绝对路径。

        Returns:
            文件内容。
        """
        pass

    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """列出目录内容。

        Args:
            path: 要列出的目录绝对路径。
            max_depth: 最大遍历深度。默认为 2。

        Returns:
            目录内容列表。
        """
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """写入文件内容。

        Args:
            path: 要写入的文件的绝对路径。
            content: 要写入的文本内容。
            append: 是否追加内容。如果为 False，文件将被创建或覆盖。
        """
        pass

    @abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        """用二进制内容更新文件。

        Args:
            path: 要更新的文件的绝对路径。
            content: 要写入的二进制内容。
        """
        pass
