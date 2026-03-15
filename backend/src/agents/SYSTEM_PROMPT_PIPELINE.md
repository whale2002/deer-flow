# System Prompt 拼接链路

本文档详细说明 DeerFlow 系统提示词的生成和拼接过程。

## 概述

系统提示词的生成入口是 [prompt.py:apply_prompt_template](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/lead_agent/prompt.py) 函数，它将多个动态组件拼接到一个基础模板中。

## 核心流程图

```
apply_prompt_template()
    │
    ├── 1. _get_memory_context(agent_name)
    │       └── 获取用户记忆上下文
    │
    ├── 2. _build_subagent_section(n)  [条件执行]
    │       └── 构建子 Agent 系统提示
    │
    ├── 3. get_skills_prompt_section(available_skills)
    │       └── 构建技能列表部分
    │
    ├── 4. get_agent_soul(agent_name)
    │       └── 获取 Agent 人设
    │
    └── 5. SYSTEM_PROMPT_TEMPLATE.format(...)
            └── 格式化最终提示词
```

## 详细组件说明

### 1. 记忆上下文 (Memory Context)

**函数**: `_get_memory_context(agent_name)`

**文件**: [prompt.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/lead_agent/prompt.py)

**流程**:
```
_get_memory_context(agent_name)
    │
    ├── get_memory_config()          # 获取记忆配置
    │       └── 检查 enabled 和 injection_enabled
    │
    ├── get_memory_data(agent_name)  # 获取记忆数据
    │       └── 从 memory.json 文件加载
    │
    └── format_memory_for_injection(memory_data, max_tokens)
            └── 格式化为 <memory>...</memory> 标签
```

**关键文件**:
- [memory/updater.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/memory/updater.py) - `get_memory_data()` 函数
- [memory/prompt.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/memory/prompt.py) - `format_memory_for_injection()` 函数

**输出格式**:
```xml
<memory>
User Context:
- Work: [工作上下文]
- Personal: [个人上下文]
- Current Focus: [当前关注点]

History:
- Recent: [最近历史]
- Earlier: [早期历史]
</memory>
```

### 2. 子 Agent 部分 (Subagent Section)

**函数**: `_build_subagent_section(max_concurrent)`

**文件**: [prompt.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/lead_agent/prompt.py)

**条件**: 仅当 `subagent_enabled=True` 时执行

**功能**:
- 生成子 Agent 系统的完整说明
- 包含并发限制 (默认 3 个并发)
- 定义任务分解和委托策略

**输出格式**:
```xml
<subagent_system>
**SUBAGENT MODE ACTIVE - DECOMPOSE, DELEGATE, SYNTHESIZE**
...
**HARD CONCURRENCY LIMIT: MAXIMUM {n} `task` CALLS PER RESPONSE**
...
</subagent_system>
```

### 3. 技能部分 (Skills Section)

**函数**: `get_skills_prompt_section(available_skills)`

**文件**: [prompt.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/lead_agent/prompt.py)

**流程**:
```
get_skills_prompt_section(available_skills)
    │
    ├── load_skills(enabled_only=True)
    │       │
    │       ├── get_skills_root_path()     # 获取技能目录路径
    │       │       └── deer-flow/skills/
    │       │
    │       ├── 扫描 public/ 和 custom/ 目录
    │       │       └── 查找 SKILL.md 文件
    │       │
    │       └── ExtensionsConfig.from_file()
    │               └── 加载技能启用状态
    │
    └── 格式化为 <skill_system>...</skill_system>
```

**关键文件**:
- [skills/loader.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/skills/loader.py) - `load_skills()` 函数
- [skills/types.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/skills/types.py) - Skill 数据类定义

**输出格式**:
```xml
<skill_system>
You have access to skills that provide optimized workflows...

<available_skills>
    <skill>
        <name>skill-name</name>
        <description>Skill description</description>
        <location>/mnt/skills/public/skill-name/SKILL.md</location>
    </skill>
</available_skills>
</skill_system>
```

### 4. Agent 人设 (Agent Soul)

**函数**: `get_agent_soul(agent_name)`

**文件**: [prompt.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/lead_agent/prompt.py)

**流程**:
```
get_agent_soul(agent_name)
    │
    └── load_agent_soul(agent_name)
            │
            ├── 确定 Agent 目录
            │       ├── 有 agent_name: agents/{agent_name}/
            │       └── 无 agent_name: base_dir/
            │
            └── 读取 SOUL.md 文件
```

**关键文件**:
- [config/agents_config.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/config/agents_config.py) - `load_agent_soul()` 函数

**输出格式**:
```xml
<soul>
[Agent 的个性、价值观和行为准则]
</soul>
```

### 5. 最终模板格式化

**模板**: `SYSTEM_PROMPT_TEMPLATE`

**文件**: [prompt.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/lead_agent/prompt.py)

**模板结构**:
```xml
<role>
You are {agent_name}, an open-source super agent.
</role>

{soul}
{memory_context}

<thinking_style>
...
{subagent_thinking}
...
</thinking_style>

<clarification_system>
...
</clarification_system>

{skills_section}

{subagent_section}

<working_directory>
...
</working_directory>

<response_style>
...
</response_style>

<citations>
...
</citations>

<critical_reminders>
...
{subagent_reminder}
...
</critical_reminders>
```

**最终追加**:
```python
prompt + f"\n<current_date>{datetime.now().strftime('%Y-%m-%d, %A')}</current_date>"
```

## 调用入口

系统提示词的生成在 Agent 创建时调用：

**文件**: [lead_agent/agent.py](file:///Users/qinhaoyu/Desktop/code/deer-flow/backend/src/agents/lead_agent/agent.py)

```python
# 5. 生成 System Prompt
system_prompt = apply_prompt_template(
    subagent_enabled=subagent_enabled,
    max_concurrent_subagents=cfg.get("max_concurrent_subagents", 3),
    agent_name=agent_name
)

# 6. 创建并返回 Agent
return create_agent(
    model=model,
    tools=tools,
    middleware=middlewares,
    system_prompt=system_prompt,
    state_schema=ThreadState,
)
```

## 数据流总结

```
┌─────────────────────────────────────────────────────────────────────┐
│                        apply_prompt_template()                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐                                               │
│  │ Memory Context   │ ← memory.json (全局或 Agent 独立)            │
│  │ <memory>...</memory>                                             │
│  └──────────────────┘                                               │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────┐                                               │
│  │ Agent Soul       │ ← SOUL.md (Agent 人设)                       │
│  │ <soul>...</soul>                                                 │
│  └──────────────────┘                                               │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────┐                                               │
│  │ Skills Section   │ ← skills/{public,custom}/*/SKILL.md          │
│  │ <skill_system>...                                                │
│  └──────────────────┘                                               │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────┐                                               │
│  │ Subagent Section │ ← 仅当 subagent_enabled=True                 │
│  │ <subagent_system>...                                             │
│  └──────────────────┘                                               │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────┐                                               │
│  │ Base Template    │ ← SYSTEM_PROMPT_TEMPLATE                      │
│  │ <role>, <thinking_style>, <clarification_system>...             │
│  └──────────────────┘                                               │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────┐                                               │
│  │ Current Date     │ ← datetime.now()                              │
│  │ <current_date>...                                                │
│  └──────────────────┘                                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    最终 System Prompt
```

## 配置依赖

| 配置项 | 来源文件 | 影响内容 |
|--------|----------|----------|
| `memory.enabled` | config.yaml | 是否启用记忆系统 |
| `memory.injection_enabled` | config.yaml | 是否注入记忆到提示词 |
| `memory.max_injection_tokens` | config.yaml | 记忆注入的最大 token 数 |
| `subagent_enabled` | 运行时参数 | 是否启用子 Agent 功能 |
| `max_concurrent_subagents` | config.yaml | 最大并发子 Agent 数 |
| `agent_name` | 运行时参数 | Agent 名称和人设 |
| `extensions_config.json` | extensions_config.json | 技能启用状态 |

## 文件索引

| 文件路径 | 主要功能 |
|----------|----------|
| `backend/src/agents/lead_agent/prompt.py` | 系统提示词模板和拼接逻辑 |
| `backend/src/agents/lead_agent/agent.py` | Agent 创建入口 |
| `backend/src/agents/memory/updater.py` | 记忆数据读取 |
| `backend/src/agents/memory/prompt.py` | 记忆格式化 |
| `backend/src/config/agents_config.py` | Agent 配置和 SOUL.md 加载 |
| `backend/src/skills/loader.py` | 技能加载 |
| `backend/src/skills/types.py` | Skill 数据类 |
| `backend/src/config/app_config.py` | 应用配置加载 |
