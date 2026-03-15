import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, TodoListMiddleware
from langchain_core.runnables import RunnableConfig

from src.agents.lead_agent.prompt import apply_prompt_template
from src.agents.middlewares.clarification_middleware import ClarificationMiddleware
from src.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from src.agents.middlewares.memory_middleware import MemoryMiddleware
from src.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from src.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
from src.agents.middlewares.title_middleware import TitleMiddleware
from src.agents.middlewares.uploads_middleware import UploadsMiddleware
from src.agents.middlewares.view_image_middleware import ViewImageMiddleware
from src.agents.thread_state import ThreadState
from src.config.agents_config import load_agent_config
from src.config.app_config import get_app_config
from src.config.summarization_config import get_summarization_config
from src.models import create_chat_model
from src.sandbox.middleware import SandboxMiddleware

logger = logging.getLogger(__name__)


def _resolve_model_name(requested_model_name: str | None = None) -> str:
    """安全地解析运行时模型名称，如果无效则回退到默认值。如果未配置模型则返回 None。"""
    app_config = get_app_config()
    default_model_name = app_config.models[0].name if app_config.models else None
    if default_model_name is None:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")

    if requested_model_name and app_config.get_model_config(requested_model_name):
        return requested_model_name

    if requested_model_name and requested_model_name != default_model_name:
        logger.warning(f"Model '{requested_model_name}' not found in config; fallback to default model '{default_model_name}'.")
    return default_model_name


def _create_summarization_middleware() -> SummarizationMiddleware | None:
    """从配置创建并配置摘要中间件。"""
    config = get_summarization_config()

    if not config.enabled:
        return None

    # 准备 trigger 参数
    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [t.to_tuple() for t in config.trigger]
        else:
            trigger = config.trigger.to_tuple()

    # 准备 keep 参数
    keep = config.keep.to_tuple()

    # 准备 model 参数
    if config.model_name:
        model = config.model_name
    else:
        # 使用轻量级模型进行摘要以节省成本
        # 如果未显式指定，则回退到默认模型
        model = create_chat_model(thinking_enabled=False)

    # 准备 kwargs
    kwargs = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }

    if config.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = config.trim_tokens_to_summarize

    if config.summary_prompt is not None:
        kwargs["summary_prompt"] = config.summary_prompt

    return SummarizationMiddleware(**kwargs)


def _create_todo_list_middleware(is_plan_mode: bool) -> TodoListMiddleware | None:
    """创建并配置 TodoList (待办事项列表) 中间件。

    Args:
        is_plan_mode: 是否启用带有 TodoList 中间件的计划模式。

    Returns:
        如果启用了计划模式，返回 TodoListMiddleware 实例，否则返回 None。
    """
    if not is_plan_mode:
        return None

    # 匹配 DeerFlow 风格的自定义 Prompt
    system_prompt = """
        <todo_list_system>
        你可以使用 `write_todos` 工具来帮助管理复杂的多步骤目标。

        **关键规则：**
        - 完成后立即标记任务为完成状态 - 不要批量完成
        - 同一时间只保持一个任务为 `in_progress`（除非任务可以并行运行）
        - 实时更新待办列表 - 让用户了解你的进度
        - 简单任务（< 3 步）不要使用此工具 - 直接完成即可

        **适用场景：**
        此工具适用于需要系统性跟踪的复杂目标：
        - 需要 3 个或以上步骤的复杂任务
        - 需要仔细规划和执行的非平凡任务
        - 用户明确要求使用待办列表
        - 用户提供了多个任务（编号或逗号分隔）
        - 计划可能需要根据中间结果调整

        **不适用场景：**
        - 简单直接的任务
        - 无关紧要的任务（< 3 步骤）
        - 纯对话或信息性请求
        - 方法显而易见只需直接执行的任务

        **最佳实践：**
        - 创建具体、可操作的任务项
        - 将复杂任务分解为更小、可管理的步骤
        - 使用清晰、描述性的任务名称
        - 移除不再相关的任务
        - 在实现过程中发现新任务时添加进去
        - 不要害怕根据结果调整计划

        **任务管理：**
        在处理复杂问题时使用它会有所帮助，简单请求则不必使用。
        </todo_list_system>
        """

    tool_description = """使用此工具创建和管理复杂工作会话的结构化任务列表。

        **重要提示：仅用于复杂任务（3 步以上）。简单请求直接完成即可。**

        ## 适用场景

        在以下情况使用此工具：
        1. **复杂多步骤任务**：需要 3 个或以上不同步骤的任务
        2. **非平凡任务**：需要仔细规划和多次操作的任务
        3. **用户明确要求**：用户直接要求使用待办列表
        4. **多个任务**：用户提供了需要完成的事项列表
        5. **动态规划**：计划可能需要根据中间结果更新

        ## 不适用场景

        以下情况跳过此工具：
        1. **任务简单明了**，可以在几步内完成
        2. **任务无关紧要**，跟踪没有好处
        3. **纯对话或信息性请求**
        4. **方法显而易见**，可以直接执行

        ## 使用方法

        1. **开始任务**：开始工作前标记为 `in_progress`
        2. **完成任务**：完成后立即标记为 `completed`
        3. **更新列表**：根据需要添加新任务、移除无关任务、更新描述
        4. **批量更新**：可以同时完成多个更新（例如完成一个任务并开始下一个）

        ## 任务状态

        - `pending`：任务尚未开始
        - `in_progress`：正在进行中（如果任务可以并行，可以有多个）
        - `completed`：任务成功完成

        ## 任务完成要求

        **重要：只有完全完成任务后才能标记为完成。**

        以下情况不要标记为完成：
        - 有未解决的问题或错误
        - 工作部分或不完整
        - 遇到阻碍无法继续
        - 无法找到必要的资源或依赖
        - 未达到质量标准

        如果被阻塞，保持 `in_progress` 状态，并创建新任务描述需要解决的内容。

        ## 最佳实践

        - 创建具体、可操作的任务项
        - 将复杂任务分解为更小、可管理的步骤
        - 使用清晰、描述性的任务名称
        - 实时更新任务状态
        - 完成后立即标记为完成（不要批量完成）
        - 移除不再相关的任务
        - **重要**：写入待办列表后，立即将第一个任务标记为 `in_progress`
        - **重要**：除非所有任务都完成，始终保持至少一个任务为 `in_progress` 以显示进度

        积极主动的任务管理展示了严谨性，确保所有要求都能顺利完成。

        **记住**：如果只需要几个工具调用就能完成任务且方法显而易见，最好直接完成任务，而不是使用此工具。
        """

    return TodoListMiddleware(system_prompt=system_prompt, tool_description=tool_description)


# ThreadDataMiddleware 必须在 SandboxMiddleware 之前，以确保 thread_id 可用
# UploadsMiddleware 应该在 ThreadDataMiddleware 之后，以访问 thread_id
# DanglingToolCallMiddleware 补全缺失的 ToolMessages，防止模型看到不完整的历史
# SummarizationMiddleware 应该尽早执行，以便在其他处理之前减少上下文
# TodoListMiddleware 应该在 ClarificationMiddleware 之前，允许管理待办事项
# TitleMiddleware 在第一次交换后生成标题
# MemoryMiddleware 将对话加入记忆更新队列 (在 TitleMiddleware 之后)
# ViewImageMiddleware 应该在 ClarificationMiddleware 之前，在 LLM 之前注入图片详情
# ClarificationMiddleware 应该最后执行，以拦截模型调用后的澄清请求
def _build_middlewares(config: RunnableConfig, model_name: str | None, agent_name: str | None = None):
    """根据运行时配置构建中间件链。

    Args:
        config: 包含可配置选项（如 is_plan_mode）的运行时配置。
        agent_name: 如果提供，MemoryMiddleware 将使用每个 Agent 独立的记忆存储。

    Returns:
        中间件实例列表。
    """
    middlewares = [ThreadDataMiddleware(), UploadsMiddleware(), SandboxMiddleware(), DanglingToolCallMiddleware()]

    # 如果启用，添加摘要中间件
    summarization_middleware = _create_summarization_middleware()
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    # 如果启用了计划模式，添加 TodoList 中间件
    is_plan_mode = config.get("configurable", {}).get("is_plan_mode", False)
    todo_list_middleware = _create_todo_list_middleware(is_plan_mode)
    if todo_list_middleware is not None:
        middlewares.append(todo_list_middleware)

    # 添加 TitleMiddleware (标题生成)
    middlewares.append(TitleMiddleware())

    # 添加 MemoryMiddleware (记忆管理，在 TitleMiddleware 之后)
    middlewares.append(MemoryMiddleware(agent_name=agent_name))

    # 仅当当前模型支持视觉时添加 ViewImageMiddleware。
    # 使用从 make_lead_agent 解析的运行时 model_name，避免使用陈旧的配置值。
    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        middlewares.append(ViewImageMiddleware())

    # 添加 SubagentLimitMiddleware 以截断过多的并行任务调用
    subagent_enabled = config.get("configurable", {}).get("subagent_enabled", False)
    if subagent_enabled:
        max_concurrent_subagents = config.get("configurable", {}).get("max_concurrent_subagents", 3)
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents))

    # ClarificationMiddleware (澄清) 应该始终排在最后
    middlewares.append(ClarificationMiddleware())
    return middlewares


def make_lead_agent(config: RunnableConfig):
    # 延迟导入以避免循环依赖
    from src.tools import get_available_tools
    from src.tools.builtins import setup_agent

    cfg = config.get("configurable", {})

    thinking_enabled = cfg.get("thinking_enabled", True)
    reasoning_effort = cfg.get("reasoning_effort", None)
    requested_model_name: str | None = cfg.get("model_name") or cfg.get("model")
    is_plan_mode = cfg.get("is_plan_mode", False)
    subagent_enabled = cfg.get("subagent_enabled", False)
    max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
    is_bootstrap = cfg.get("is_bootstrap", False)
    agent_name = cfg.get("agent_name")

    agent_config = load_agent_config(agent_name) if not is_bootstrap else None
    # 使用自定义 Agent 模型，或回退到全局/默认模型解析
    agent_model_name = agent_config.model if agent_config and agent_config.model else _resolve_model_name()

    # 最终模型名称解析：请求覆盖 > Agent 配置 > 全局默认
    model_name = requested_model_name or agent_model_name

    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None

    if model_config is None:
        raise ValueError("No chat model could be resolved. Please configure at least one model in config.yaml or provide a valid 'model_name'/'model' in the request.")
    if thinking_enabled and not model_config.supports_thinking:
        logger.warning(f"Thinking mode is enabled but model '{model_name}' does not support it; fallback to non-thinking mode.")
        thinking_enabled = False

    logger.info(
        "Create Agent(%s) -> thinking_enabled: %s, reasoning_effort: %s, model_name: %s, is_plan_mode: %s, subagent_enabled: %s, max_concurrent_subagents: %s",
        agent_name or "default",
        thinking_enabled,
        reasoning_effort,
        model_name,
        is_plan_mode,
        subagent_enabled,
        max_concurrent_subagents,
    )

    # 注入运行元数据用于 LangSmith 跟踪标记
    if "metadata" not in config:
        config["metadata"] = {}

    config["metadata"].update(
        {
            "agent_name": agent_name or "default",
            "model_name": model_name or "default",
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "is_plan_mode": is_plan_mode,
            "subagent_enabled": subagent_enabled,
        }
    )

    if is_bootstrap:
        # 特殊的引导 Agent，具有最小的 Prompt，用于初始自定义 Agent 创建流程
        system_prompt = apply_prompt_template(subagent_enabled=subagent_enabled, max_concurrent_subagents=max_concurrent_subagents, available_skills=set(["bootstrap"]))

        return create_agent(
            model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
            tools=get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled) + [setup_agent],
            middleware=_build_middlewares(config, model_name=model_name),
            system_prompt=system_prompt,
            state_schema=ThreadState,
        )

    # 默认的主导 Agent (行为不变)
    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, reasoning_effort=reasoning_effort),
        tools=get_available_tools(model_name=model_name, groups=agent_config.tool_groups if agent_config else None, subagent_enabled=subagent_enabled),
        middleware=_build_middlewares(config, model_name=model_name, agent_name=agent_name),
        system_prompt=apply_prompt_template(subagent_enabled=subagent_enabled, max_concurrent_subagents=max_concurrent_subagents, agent_name=agent_name),
        state_schema=ThreadState,
    )
