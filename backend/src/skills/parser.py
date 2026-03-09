"""技能解析器 (Skill Parser)。"""

import re
from pathlib import Path

from .types import Skill


def parse_skill_file(skill_file: Path, category: str, relative_path: Path | None = None) -> Skill | None:
    """解析 SKILL.md 文件并提取元数据。

    该函数读取 SKILL.md 文件的 Frontmatter (头部元数据) 部分。

    Args:
        skill_file: SKILL.md 文件的路径。
        category: 技能类别 ('public' 或 'custom')。
        relative_path: 相对路径。

    Returns:
        如果解析成功返回 Skill 对象，否则返回 None。
    """
    if not skill_file.exists() or skill_file.name != "SKILL.md":
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")

        # 提取 YAML Front Matter
        # 模式: 以 --- 开头，以 --- 结束的块
        front_matter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)

        if not front_matter_match:
            return None

        front_matter = front_matter_match.group(1)

        # 解析 YAML Front Matter (简单的键值对解析)
        metadata = {}
        for line in front_matter.split("\n"):
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        # 提取必需字段
        name = metadata.get("name")
        description = metadata.get("description")

        if not name or not description:
            return None

        license_text = metadata.get("license")

        return Skill(
            name=name,
            description=description,
            license=license_text,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            relative_path=relative_path or Path(skill_file.parent.name),
            category=category,
            enabled=True,  # 默认为启用，实际状态来自配置文件
        )

    except Exception as e:
        print(f"Error parsing skill file {skill_file}: {e}")
        return None
