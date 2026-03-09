"""技能类型定义 (Skill Types)。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """表示一个技能及其元数据和文件路径。"""

    name: str  # 技能名称
    description: str  # 技能描述
    license: str | None  # 许可证信息
    skill_dir: Path  # 技能所在的目录路径
    skill_file: Path  # SKILL.md 文件的完整路径
    relative_path: Path  # 从类别根目录 (skills/{category}) 到技能目录的相对路径
    category: str  # 'public' 或 'custom'
    enabled: bool = False  # 此技能是否已启用

    @property
    def skill_path(self) -> str:
        """返回从类别根目录 (skills/{category}) 到此技能目录的相对路径字符串。"""
        path = self.relative_path.as_posix()
        return "" if path == "." else path

    def get_container_path(self, container_base_path: str = "/mnt/skills") -> str:
        """获取此技能在沙箱容器中的完整挂载路径。

        Args:
            container_base_path: 技能在容器中的挂载基路径 (默认为 /mnt/skills)。

        Returns:
            技能目录的完整容器路径。
        """
        category_base = f"{container_base_path}/{self.category}"
        skill_path = self.skill_path
        if skill_path:
            return f"{category_base}/{skill_path}"
        return category_base

    def get_container_file_path(self, container_base_path: str = "/mnt/skills") -> str:
        """获取此技能的主文件 (SKILL.md) 在沙箱容器中的完整路径。

        Args:
            container_base_path: 技能在容器中的挂载基路径 (默认为 /mnt/skills)。

        Returns:
            SKILL.md 文件的完整容器路径。
        """
        return f"{self.get_container_path(container_base_path)}/SKILL.md"

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, description={self.description!r}, category={self.category!r})"
