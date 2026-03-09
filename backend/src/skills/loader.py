"""技能加载器 (Skills Loader)。"""

import os
from pathlib import Path

from .parser import parse_skill_file
from .types import Skill


def get_skills_root_path() -> Path:
    """获取技能目录的根路径。

    Returns:
        技能目录的路径 (deer-flow/skills)。
    """
    # backend 目录是当前文件 (loader.py) 的上上上级目录 (src -> skills -> loader.py)
    backend_dir = Path(__file__).resolve().parent.parent.parent
    # skills 目录与 backend 目录同级
    skills_dir = backend_dir.parent / "skills"
    return skills_dir


def load_skills(skills_path: Path | None = None, use_config: bool = True, enabled_only: bool = False) -> list[Skill]:
    """从技能目录加载所有技能。

    扫描 `public` 和 `custom` 两个技能子目录，解析其中的 `SKILL.md` 文件以提取元数据。
    技能的启用状态 (enabled/disabled) 由 `extensions_config.json` 配置文件决定。

    Args:
        skills_path: 可选的自定义技能目录路径。
                     如果未提供且 use_config 为 True，则从配置中读取路径。
                     否则默认为 `deer-flow/skills`。
        use_config: 是否从配置中加载技能路径 (默认: True)。
        enabled_only: 如果为 True，则仅返回已启用的技能 (默认: False)。

    Returns:
        按名称排序的 Skill 对象列表。
    """
    if skills_path is None:
        if use_config:
            try:
                from src.config import get_app_config

                config = get_app_config()
                skills_path = config.skills.get_skills_path()
            except Exception:
                # 如果配置加载失败，回退到默认路径
                skills_path = get_skills_root_path()
        else:
            skills_path = get_skills_root_path()

    if not skills_path.exists():
        return []

    skills = []

    # 扫描 public 和 custom 目录
    for category in ["public", "custom"]:
        category_path = skills_path / category
        if not category_path.exists() or not category_path.is_dir():
            continue

        for current_root, dir_names, file_names in os.walk(category_path):
            # 保持遍历顺序确定性，并跳过隐藏目录
            dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
            if "SKILL.md" not in file_names:
                continue

            skill_file = Path(current_root) / "SKILL.md"
            relative_path = skill_file.parent.relative_to(category_path)

            skill = parse_skill_file(skill_file, category=category, relative_path=relative_path)
            if skill:
                skills.append(skill)

    # 加载技能状态配置并更新启用状态
    # 注意: 我们使用 ExtensionsConfig.from_file() 而不是 get_extensions_config()
    # 是为了确保总是从磁盘读取最新配置。这保证了通过 Gateway API (运行在独立进程)
    # 所做的更改能立即反映在 LangGraph Server 加载技能时。
    try:
        from src.config.extensions_config import ExtensionsConfig

        extensions_config = ExtensionsConfig.from_file()
        for skill in skills:
            skill.enabled = extensions_config.is_skill_enabled(skill.name, skill.category)
    except Exception as e:
        # 如果配置加载失败，默认全部启用
        print(f"Warning: Failed to load extensions config: {e}")

    # 如果请求，按启用状态过滤
    if enabled_only:
        skills = [skill for skill in skills if skill.enabled]

    # 按名称排序以保持顺序一致
    skills.sort(key=lambda s: s.name)

    return skills
