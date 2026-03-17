# DeerFlow 工具调用链路分析

> 从模型识别到工具执行的完整流程
> 最后更新：2026-03-18

---

## 一、整体架构概览

```
用户输入："帮我写个 Python 函数"
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 模型决策 (LLM)                                          │
│    - 分析用户意图                                           │
│    - 决定是否调用工具                                       │
│    - 选择调用哪个工具                                       │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 工具绑定 (Tool Binding)                                 │
│    - LangChain 框架将工具绑定到模型                         │
│    - 模型输出 tool_calls 格式                               │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 工具执行 (Tool Execution)                               │
│    - 解析 tool_calls                                        │
│    - 查找对应工具函数                                       │
│    - 执行并返回结果                                         │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
        结果返回给模型 → 继续对话或结束
```

---

## 二、工具定义与注册

### 2.1 工具来源

DeerFlow 的工具来自三个地方：

| 来源         | 说明                       | 示例                                 |
| ------------ | -------------------------- | ------------------------------------ |
| **配置文件** | `AppConfig.tools` 动态加载 | `src.sandbox.tools:bash_tool`        |
| **内置工具** | 始终可用的核心工具         | `present_files`, `ask_clarification` |
| **MCP 工具** | MCP 服务器提供的工具       | 第三方服务                           |

### 2.2 配置文件加载

工具在 `src/config/app_config.py` 中定义：

```python
class AppConfig(BaseModel):
    tools: list[ToolConfig] = Field(default_factory=list)
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list)
```

### 2.3 工具获取函数

`src/tools/tools.py` 中的 `get_available_tools()` 函数：

```python
def get_available_tools(
    groups: list[str] | None = None,
    include_mcp: bool = True,
    model_name: str | None = None,
    subagent_enabled: bool = False,
) -> list[BaseTool]:
    # 1. 加载配置文件中的 Python 工具
    loaded_tools = [
        resolve_variable(tool.use, BaseTool)
        for tool in config.tools
        if groups is None or tool.group in groups
    ]

    # 2. 加载 MCP 工具
    mcp_tools = get_cached_mcp_tools() if include_mcp else []

    # 3. 添加内置工具
    builtin_tools = BUILTIN_TOOLS.copy()

    # 4. 根据模式添加子代理工具
    if subagent_enabled:
        builtin_tools.extend(SUBAGENT_TOOLS)

    return loaded_tools + builtin_tools + mcp_tools
```

### 2.4 工具定义方式

使用 LangChain 的 `@tool` 装饰器：

```python
from langchain.tools import tool, ToolRuntime

@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """在 Linux 环境中执行 bash 命令。

    Args:
        description: 用简短的话解释你为什么运行这个命令。
        command: 要执行的 bash 命令。
    """
    sandbox = ensure_sandbox_initialized(runtime)
    return sandbox.execute_command(command)
```

---

## 三、模型如何识别需要调用工具

### 3.1 工具绑定机制

在创建 Agent 时，工具被绑定到模型：

```python
# src/agents/lead_agent/agent.py
tools = get_available_tools(...)
agent = create_agent(
    model=model,
    tools=tools,  # 绑定工具到模型
    ...
)
```

LangChain 内部会：

1. 将每个工具的 schema（名称、描述、参数）发送给模型
2. 模型根据用户意图和工具描述决定是否调用工具

### 3.2 System Prompt 中的工具说明

工具的 `description` 和函数的 `docstring` 会被提取成工具说明，告诉模型什么时候该用什么工具。

例如 `bash_tool` 的 docstring：

```python
"""在 Linux 环境中执行 bash 命令。

- 使用 `python` 运行 Python 代码。
- 使用 `pip install` 安装 Python 包。

Args:
    description: 用简短的话解释你为什么运行这个命令。
    command: 要执行的 bash 命令。文件和目录始终使用绝对路径。
"""
```

---

## 四、工具执行链路详解

### 4.1 完整流程图

```
模型输出 tool_calls
        │
        ▼
┌─────────────────────────────────────────────┐
│ LangChain 框架解析                           │
│ - 解析 tool_name                           │
│ - 解析 arguments (JSON)                    │
│ - 创建 ToolCall 对象                        │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│ 工具查找                                     │
│ - 根据 tool_name 查找对应函数               │
│ - src.sandbox.tools:bash_tool → bash_tool  │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│ 参数注入                                     │
│ - runtime (运行时上下文)                    │
│ - description (描述)                        │
│ - command (命令)                            │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│ 执行工具函数                                 │
│ - 初始化 sandbox                            │
│ - 确保目录存在                               │
│ - 执行实际命令                              │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│ 结果转换                                     │
│ - 返回字符串结果                           │
│ - 转换为 ToolMessage                        │
│ - 加入消息列表                             │
└─────────────────────────────────────────────┘
        │
        ▼
      模型继续处理
```

### 4.2 关键代码路径

#### 4.2.1 bash_tool 执行流程

```python
# src/sandbox/tools.py

@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """执行 bash 命令"""

    # 1. 确保 sandbox 已初始化
    sandbox = ensure_sandbox_initialized(runtime)

    # 2. 确保线程目录存在
    ensure_thread_directories_exist(runtime)

    # 3. 本地 sandbox 需要路径转换
    if is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        command = replace_virtual_paths_in_command(command, thread_data)

    # 4. 执行命令
    return sandbox.execute_command(command)
```

#### 4.2.2 read_file_tool 执行流程

```python
@tool("read_file", parse_docstring=True)
def read_file_tool(runtime, description: str, path: str, start_line=None, end_line=None):
    # 1. 获取 sandbox
    sandbox = ensure_sandbox_initialized(runtime)

    # 2. 路径转换
    if is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        path = replace_virtual_path(path, thread_data)

    # 3. 读取文件
    content = sandbox.read_file(path)

    # 4. 行范围截断
    if start_line is not None and end_line is not None:
        content = "\n".join(content.splitlines()[start_line - 1 : end_line])

    return content
```

#### 4.2.3 write_file_tool 执行流程

```python
@tool("write_file", parse_docstring=True)
def write_file_tool(runtime, description: str, path: str, content: str, ...):
    sandbox = ensure_sandbox_initialized(runtime)

    if is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        path = replace_virtual_path(path, thread_data)

    # 写入文件
    sandbox.write_file(path, content)

    return f"File written successfully: {path}"
```

---

## 五、关键组件解析

### 5.1 ToolRuntime

`ToolRuntime` 是 LangChain 提供的运行时上下文，包含：

```python
@dataclass
class ToolRuntime(Generic[ContextT, StateT]):
    context: ContextT          # 运行时上下文（sandbox 信息等）
    state: StateT             # Agent 状态（消息列表等）
    tool_call: InjectedToolCallId  # 工具调用 ID
    config: RunnableConfig    # 运行配置
```

### 5.2 虚拟路径系统

工具使用虚拟路径，运行时转换为实际路径：

| 虚拟路径                   | 实际路径                                   |
| -------------------------- | ------------------------------------------ |
| `/mnt/user-data/workspace` | `{data_dir}/threads/{thread_id}/workspace` |
| `/mnt/user-data/uploads`   | `{data_dir}/threads/{thread_id}/uploads`   |
| `/mnt/user-data/outputs`   | `{data_dir}/threads/{thread_id}/outputs`   |

### 5.3 Sandbox 初始化

```python
def ensure_sandbox_initialized(runtime):
    """确保 sandbox 已初始化"""
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        sandbox_provider = get_sandbox_provider()
        sandbox_id = sandbox_provider.acquire(runtime.config["configurable"]["thread_id"])
        sandbox = sandbox_provider.get(sandbox_id)
        runtime.state["sandbox"] = {"id": sandbox_id}
        return sandbox
    return sandbox_provider.get(sandbox_state["id"])
```

---

## 六、子代理 (Subagent) 的工具调用

### 6.1 子代理类型

DeerFlow 有两种子代理：

| 类型              | 用途           | 工具                            |
| ----------------- | -------------- | ------------------------------- |
| `bash`            | 执行 bash 命令 | bash, ls, read_file, write_file |
| `general-purpose` | 通用任务       | 所有工具                        |

### 6.2 子代理工具调用流程

```
主 Agent 调用 task 工具
        │
        ▼
task_tool 执行
        │
        ▼
SubagentExecutor 创建子 Agent
        │
        ▼
子 Agent 独立执行（有自己的工具集）
        │
        ▼
结果返回给主 Agent
```

### 6.3 子代理配置

```python
# src/subagents/builtins/bash_agent.py
BASH_AGENT_CONFIG = SubagentConfig(
    name="bash",
    description="""Command execution specialist...""",
    system_prompt="""You are a bash command execution specialist...""",
    tools=["bash", "ls", "read_file", "write_file", "str_replace"],
    disallowed_tools=["task", "ask_clarification", "present_files"],
    max_turns=30,
)
```

---

## 七、文件上传与转换

### 7.1 上传流程

```
用户选择文件
        │
        ▼
POST /api/threads/{thread_id}/uploads
        │
        ▼
gateway/routers/uploads.py
        │
        ▼
保存到 {data_dir}/threads/{thread_id}/uploads/
        │
        ▼
如果是 PDF/PPT/Excel/DOCX
        │
        ▼
使用 markitdown 转换为 Markdown
```

### 7.2 转换代码

```python
# src/gateway/routers/uploads.py
async def convert_file_to_markdown(file_path: Path) -> Path | None:
    from markitdown import MarkItDown
    md = MarkItDown()
    result = md.convert(str(file_path))

    md_path = file_path.with_suffix(".md")
    md_path.write_text(result.text_content)
    return md_path
```

---

## 八、关键文件索引

| 功能         | 文件路径                               |
| ------------ | -------------------------------------- |
| 工具获取     | `src/tools/tools.py`                   |
| 沙箱工具定义 | `src/sandbox/tools.py`                 |
| Agent 创建   | `src/agents/lead_agent/agent.py`       |
| 子代理执行器 | `src/subagents/executor.py`            |
| 子代理配置   | `src/subagents/config.py`              |
| Bash 子代理  | `src/subagents/builtins/bash_agent.py` |
| 文件上传     | `src/gateway/routers/uploads.py`       |
| 沙箱管理     | `src/sandbox/sandbox.py`               |

---

## 九、总结

DeerFlow 的工具调用链路：

1. **工具注册** → 配置文件 + 内置工具 + MCP 工具
2. **模型决策** → 根据 System Prompt 和工具描述决定调用
3. **工具绑定** → LangChain 框架将工具 schema 发送给模型
4. **执行链路** → 解析 tool_calls → 查找函数 → 注入 runtime → 执行 → 返回结果
5. **路径隔离** → 虚拟路径 + thread_id 确保多用户安全

核心设计原则：

- **隔离性**：每个用户的文件在独立目录
- **可扩展性**：工具通过配置和 MCP 动态加载
- **安全性**：本地 sandbox 限制命令执行范围
