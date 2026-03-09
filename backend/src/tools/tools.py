import logging

from langchain.tools import BaseTool

from src.config import get_app_config
from src.reflection import resolve_variable
from src.tools.builtins import ask_clarification_tool, present_file_tool, task_tool, view_image_tool

logger = logging.getLogger(__name__)

# 内置工具列表：这些工具始终可用
BUILTIN_TOOLS = [
    present_file_tool,  # 文件展示工具 (用于在 UI 上渲染文件)
    ask_clarification_tool,  # 澄清提问工具 (用于主动询问用户)
]

# 子智能体 (Subagent) 工具列表：仅在启用子智能体模式时加载
SUBAGENT_TOOLS = [
    task_tool,  # 任务委派工具 (用于启动并行子智能体)
    # task_status_tool 不再暴露给 LLM (后端会在内部处理轮询逻辑)
]


def get_available_tools(
    groups: list[str] | None = None,
    include_mcp: bool = True,
    model_name: str | None = None,
    subagent_enabled: bool = False,
) -> list[BaseTool]:
    """从配置中获取所有可用工具。

    注意: MCP 工具应在应用程序启动时使用 src.mcp 模块中的
    `initialize_mcp_tools()` 进行初始化。

    Args:
        groups: 可选的工具组列表进行过滤。如果为 None，则加载所有工具。
                (类似于前端根据权限过滤路由)
        include_mcp: 是否包含来自 MCP 服务器的工具 (默认: True)。
        model_name: 可选的模型名称，用于确定是否应包含视觉工具。
        subagent_enabled: 是否包含子智能体工具 (task, task_status)。
                          (只有 Ultra 模式才会开启)

    Returns:
        可用工具的列表 (List[BaseTool])。
    """
    config = get_app_config()

    # 1. 加载 config.yaml 中配置的 Python 工具
    # 使用反射 (Reflection) 机制动态加载类
    loaded_tools = [resolve_variable(tool.use, BaseTool) for tool in config.tools if groups is None or tool.group in groups]

    # 2. 加载缓存的 MCP 工具 (如果启用)
    # 注意: 我们使用 ExtensionsConfig.from_file() 而不是 config.extensions
    # 来始终从磁盘读取最新配置。这确保了通过 Gateway API (运行在独立进程)
    # 所做的更改能立即反映在加载 MCP 工具时。
    mcp_tools = []
    if include_mcp:
        try:
            from src.config.extensions_config import ExtensionsConfig
            from src.mcp.cache import get_cached_mcp_tools

            extensions_config = ExtensionsConfig.from_file()
            if extensions_config.get_enabled_mcp_servers():
                mcp_tools = get_cached_mcp_tools()
                if mcp_tools:
                    logger.info(f"Using {len(mcp_tools)} cached MCP tool(s)")
        except ImportError:
            logger.warning("MCP module not available. Install 'langchain-mcp-adapters' package to enable MCP tools.")
        except Exception as e:
            logger.error(f"Failed to get cached MCP tools: {e}")

    # 3. 准备内置工具
    builtin_tools = BUILTIN_TOOLS.copy()

    # 4. 如果启用了子智能体模式，添加相关工具
    if subagent_enabled:
        builtin_tools.extend(SUBAGENT_TOOLS)
        logger.info("Including subagent tools (task)")

    # 如果未指定 model_name，使用第一个模型 (默认)
    if model_name is None and config.models:
        model_name = config.models[0].name

    # 5. 仅当模型支持视觉时，添加 view_image_tool
    model_config = config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        builtin_tools.append(view_image_tool)
        logger.info(f"Including view_image_tool for model '{model_name}' (supports_vision=True)")

    # 6. 合并所有工具并返回
    return loaded_tools + builtin_tools + mcp_tools
