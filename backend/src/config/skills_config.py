from pathlib import Path

from pydantic import BaseModel, Field


class SkillsConfig(BaseModel):
    """技能系统配置"""

    path: str | None = Field(
        default=None,
        description="技能目录路径。如果未指定，默认为相对于后端目录的 ../skills",
    )
    container_path: str = Field(
        default="/mnt/skills",
        description="技能在沙箱容器中挂载的路径",
    )

    def get_skills_path(self) -> Path:
        """
        获取解析后的技能目录路径。

        Returns:
            技能目录的 Path 对象
        """
        if self.path:
            # 使用配置的路径（可以是绝对路径或相对路径）
            path = Path(self.path)
            if not path.is_absolute():
                # 如果是相对路径，则从当前工作目录解析
                path = Path.cwd() / path
            return path.resolve()
        else:
            # 默认：相对于后端目录的 ../skills
            from src.skills.loader import get_skills_root_path

            return get_skills_root_path()

    def get_skill_container_path(self, skill_name: str, category: str = "public") -> str:
        """
        获取特定技能的完整容器路径。

        Args:
            skill_name: 技能名称（目录名）
            category: 技能类别（public 或 custom）

        Returns:
            容器中技能的完整路径
        """
        return f"{self.container_path}/{category}/{skill_name}"
