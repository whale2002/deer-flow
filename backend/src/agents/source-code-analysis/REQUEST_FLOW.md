# DeerFlow 请求链路分析

> 从前端输入"你好"开始的完整链路追踪
> 最后更新：2026-03-09

---

## 📊 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户输入"你好"                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1️⃣ Frontend (Next.js + React)                                             │
│     - 聊天界面组件                                                          │
│     - useThreadStream Hook                                                 │
│     - LangGraph SDK Client                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTP + SSE (Server-Sent Events)
                                      │ streamMode: ["values", "messages-tuple", "custom"]
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2️⃣ Nginx Reverse Proxy (Port 2026)                                        │
│     - /api/langgraph/* → LangGraph Server (2024)                           │
│     - /api/* → Gateway API (8001)                                          │
│     - /* → Frontend (3000)                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3️⃣ LangGraph Server (Port 2024)                                           │
│     - Graph: lead_agent (src/agents:make_lead_agent)                       │
│     - Checkpointer: 状态持久化                                              │
│     - 流式输出 Events                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  4️⃣ Agent 核心处理                                                          │
│     ┌─────────────────────────────────────────────────────────┐            │
│     │              Agent 执行流程                              │            │
│     │                                                         │            │
│     │  ┌─────────────┐                                       │            │
│     │  │ System      │ ← Prompt 模板 + 记忆注入               │            │
│     │  │ Prompt      │                                       │            │
│     │  └─────────────┘                                       │            │
│     │         │                                              │            │
│     │         ▼                                              │            │
│     │  ┌─────────────────────────────────────────────────┐   │            │
│     │  │ Middleware Chain (Before Model)                 │   │            │
│     │  │ 1. ThreadData → 2. Uploads → 3. Sandbox         │   │            │
│     │  │ 4. DanglingToolCall → 5. Summarization          │   │            │
│     │  └─────────────────────────────────────────────────┘   │            │
│     │         │                                              │            │
│     │         ▼                                              │            │
│     │  ┌─────────────────────────────────────────────────┐   │            │
│     │  │ LLM (Chat Model)                                │   │            │
│     │  │ - 支持 Thinking/Vision                         │   │            │
│     │  │ - 可调用 Tools                                  │   │            │
│     │  └─────────────────────────────────────────────────┘   │            │
│     │         │                                              │            │
│     │         ▼                                              │            │
│     │  ┌─────────────────────────────────────────────────┐   │            │
│     │  │ Middleware Chain (After Model)                  │   │            │
│     │  │ 6. TodoList → 7. Title → 8. Memory              │   │            │
│     │  │ 9. ViewImage → 10. SubagentLimit                │   │            │
│     │  │ 11. Clarification                               │   │            │
│     │  └─────────────────────────────────────────────────┘   │            │
│     │         │                                              │            │
│     │         ▼                                              │            │
│     │  ┌─────────────────────────────────────────────────┐   │            │
│     │  │ Tool Execution                                  │   │            │
│     │  │ - bash, read_file, write_file                  │   │            │
│     │  │ - task (Subagent)                              │   │            │
│     │  │ - MCP Tools                                    │   │            │
│     │  └─────────────────────────────────────────────────┘   │            │
│     └─────────────────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ SSE Events 实时返回
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  5️⃣ Frontend 接收流式响应                                                    │
│     - onLangChainEvent → 工具事件                                           │
│     - onUpdateEvent → 状态更新                                              │
│     - onCustomEvent → 子代理运行事件                                        │
│     - onFinish → 完成回调                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  6️⃣ UI 渲染更新                                                              │
│     - 消息列表更新                                                          │
│     - 产物/任务状态更新                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细链路分解

### Step 1: 前端输入处理

**文件**: `frontend/src/core/threads/hooks.ts`

当用户在聊天输入框输入"你好"并点击发送：

```typescript
// 1. 用户调用 sendMessage
sendMessage(threadId, { text: "你好" }, extraContext)

// 2. 创建 Optimistic 消息（立即显示，提升体验）
const optimisticHumanMsg: Message = {
  type: "human",
  id: `opt-human-${Date.now()}`,
  content: [{ type: "text", text: "你好" }],
};
setOptimisticMessages([optimisticHumanMsg]);

// 3. 构建提交配置
await thread.submit(
  { messages: [{ type: "human", content: [{ type: "text", text: "你好" }] }] },
  {
    threadId: threadId,
    streamSubgraphs: true,          // 启用子图流式输出
    streamResumable: true,          // 支持断点续传
    streamMode: ["values", "messages-tuple", "custom"],  // 流模式
    config: {
      recursion_limit: 1000,
      thinking_enabled: context.mode !== "flash",     // 思考模式
      is_plan_mode: context.mode === "pro" || context.mode === "ultra",
      subagent_enabled: context.mode === "ultra",     // 子代理模式
    },
  }
);
```

#### 关键点

| 参数 | 作用 |
|------|------|
| `streamMode` | 接收三种事件：`values`(全量状态), `messages-tuple`(消息增量), `custom`(自定义事件) |
| `thinking_enabled` | 根据模式决定是否启用模型思考 |
| `subagent_enabled` | Ultra 模式启用子代理 delegation |

---

### Step 2: LangGraph SDK 建立流式连接

**文件**: `frontend/src/core/api/api-client.ts`

```typescript
import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

let _singleton: LangGraphClient | null = null;

export function getAPIClient(isMock?: boolean): LangGraphClient {
  _singleton ??= new LangGraphClient({
    apiUrl: getLangGraphBaseURL(isMock),  // 默认：/api/langgraph
  });
  return _singleton;
}
```

#### HTTP 请求示例

```
POST /api/langgraph/assistants/lead_agent/threads/{threadId}/runs/stream
Content-Type: application/json

{
  "input": {
    "messages": [{ "type": "human", "content": [{ "type": "text", "text": "你好" }] }]
  },
  "config": {
    "recursion_limit": 1000,
    "configurable": {
      "thinking_enabled": true,
      "subagent_enabled": false
    }
  },
  "streamMode": ["values", "messages-tuple", "custom"],
  "streamSubgraphs": true
}
```

---

### Step 3: Nginx 反向代理

**配置文件**: `nginx.conf`

```nginx
# /api/langgraph/* 请求代理到 LangGraph Server
location /api/langgraph/ {
    proxy_pass http://127.0.0.1:2024;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;

    # SSE 支持
    proxy_cache off;
    proxy_buffering off;
    proxy_read_timeout 86400s;  # 长连接
}

# /api/* (其他) 请求代理到 Gateway API
location /api/ {
    proxy_pass http://127.0.0.1:8001;
}

# /* (静态资源) 代理到 Frontend
location / {
    proxy_pass http://127.0.0.1:3000;
}
```

---

### Step 4: LangGraph Server 接收请求

**文件**: `backend/langgraph.json`

```json
{
  "$schema": "https://langgra.ph/schema.json",
  "dependencies": ["."],
  "env": ".env",
  "graphs": {
    "lead_agent": "src.agents:make_lead_agent"  // ← Agent 工厂函数
  },
  "checkpointer": {
    "path": "./src/agents/checkpointer/async_provider.py:make_checkpointer"
  }
}
```

#### LangGraph Server 启动流程

1. 读取 `langgraph.json` 配置
2. 导入 `make_lead_agent` 工厂函数
3. 注册 checkpointer 用于状态持久化
4. 监听端口 2024，等待流式请求

---

### Step 5: Agent 工厂创建实例

**文件**: `backend/src/agents/lead_agent/agent.py`

```python
def make_lead_agent(config: RunnableConfig):
    # 1. 从配置提取运行时参数
    cfg = config.get("configurable", {})
    thinking_enabled = cfg.get("thinking_enabled", True)
    model_name = cfg.get("model_name")
    is_plan_mode = cfg.get("is_plan_mode", False)
    subagent_enabled = cfg.get("subagent_enabled", False)
    agent_name = cfg.get("agent_name")

    # 2. 创建 LLM 模型
    model = create_chat_model(
        name=model_name,
        thinking_enabled=thinking_enabled,
        reasoning_effort=cfg.get("reasoning_effort")
    )

    # 3. 加载可用工具集
    tools = get_available_tools(
        model_name=model_name,
        groups=agent_config.tool_groups if agent_config else None,
        subagent_enabled=subagent_enabled
    )

    # 4. 构建中间件链
    middlewares = _build_middlewares(
        config,
        model_name=model_name,
        agent_name=agent_name
    )

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

---

### Step 6: 中间件链执行

**文件**: `backend/src/agents/lead_agent/agent.py`

中间件按顺序执行，形成一个处理管道：

```python
def _build_middlewares(config, model_name, agent_name=None):
    middlewares = [
        # --- Before Model ---
        ThreadDataMiddleware(),      # 1. 初始化线程目录
        UploadsMiddleware(),         # 2. 注入上传文件列表
        SandboxMiddleware(),         # 3. 获取沙箱环境
        DanglingToolCallMiddleware(),# 4. 补全缺失的 ToolMessages

        # --- 可选：上下文总结 ---
        SummarizationMiddleware(),   # 5. 接近 token 限制时总结

        # --- After Model ---
        TodoListMiddleware(),        # 6. 任务列表 (Plan Mode)
        TitleMiddleware(),           # 7. 生成对话标题
        MemoryMiddleware(),          # 8. 记忆队列
        ViewImageMiddleware(),       # 9. 图片注入 (Vision 模型)
        SubagentLimitMiddleware(),   # 10. 子代理限流
        ClarificationMiddleware(),   # 11. 澄清拦截
    ]
    return middlewares
```

#### 中间件执行时序

```
用户消息 "你好"
    │
    ▼
┌─────────────────────────────────────────────┐
│ Before Model 中间件                         │
├─────────────────────────────────────────────┤
│ 1. ThreadDataMiddleware                     │
│    → 创建 /workspace, /uploads, /outputs    │
│ 2. UploadsMiddleware                        │
│    → 检查新上传文件，注入到消息             │
│ 3. SandboxMiddleware                        │
│    → 获取 sandbox_id 放入 state             │
│ 4. DanglingToolCallMiddleware               │
│    → 检查是否有未完成的 tool_calls          │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ LLM 调用                                     │
│ - System Prompt + Messages                  │
│ - Tools 绑定                                 │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ After Model 中间件                          │
├─────────────────────────────────────────────┤
│ 6. TodoListMiddleware (可选)                │
│    → 管理待办事项列表                        │
│ 7. TitleMiddleware                          │
│    → 第一次交互后生成标题                    │
│ 8. MemoryMiddleware                         │
│    → 过滤对话，排队等待记忆更新             │
│ 9. ViewImageMiddleware (可选)               │
│    → 注入图片 base64 数据                     │
│ 10. SubagentLimitMiddleware (可选)          │
│    → 截断多余的 task 调用                     │
│ 11. ClarificationMiddleware                 │
│    → 拦截 ask_clarification 请求             │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ Tool Execution (如果有 tool_calls)          │
├─────────────────────────────────────────────┤
│ - bash, read_file, write_file              │
│ - task (Subagent delegation)               │
│ - MCP tools                                │
└─────────────────────────────────────────────┘
```

---

### Step 7: System Prompt 注入

**文件**: `backend/src/agents/lead_agent/prompt.py`

```python
SYSTEM_PROMPT_TEMPLATE = """
<role>
You are {agent_name}, an open-source super agent.
</role>

{soul}                    # Agent 人设 (SOUL.md)
{memory_context}          # 长期记忆注入

<thinking_style>
- Think concisely and strategically about the user's request BEFORE taking action
- Break down the task: What is clear? What is ambiguous? What is missing?
- **PRIORITY CHECK: If anything is unclear, missing, or has multiple interpretations, you MUST ask for clarification FIRST**
</thinking_style>

<clarification_system>
**WORKFLOW PRIORITY: CLARIFY → PLAN → ACT**
1. **FIRST**: Analyze the request - identify what's unclear, missing, or ambiguous
2. **SECOND**: If clarification is needed, call `ask_clarification` tool IMMEDIATELY
3. **THIRD**: Only after all clarifications are resolved, proceed with execution
</clarification_system>

{skills_section}          # 可用技能列表
{subagent_section}        # 子代理系统说明 (可选)

<working_directory>
- User uploads: `/mnt/user-data/uploads`
- User workspace: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`
</working_directory>

<response_style>
- Clear and Concise
- Natural Tone: Use paragraphs and prose
- Action-Oriented: Focus on delivering results
</response_style>

<critical_reminders>
- **Clarification First**: ALWAYS clarify unclear/missing/ambiguous requirements BEFORE starting work
- **Skill First**: Always load the relevant skill before starting complex tasks
- **Output Files**: Final deliverables must be in `/mnt/user-data/outputs`
</critical_reminders>

<current_date>{date}</current_date>
"""
```

---

### Step 8: 流式响应事件

LangGraph Server 通过 SSE (Server-Sent Events) 实时推送事件：

#### 事件类型

| 事件类型 | 描述 | 前端处理 |
|---------|------|---------|
| `values` | 完整状态快照 | `onUpdateEvent()` - 更新标题、消息列表 |
| `messages-tuple` | 单条消息增量 | 追加新消息到列表 |
| `custom` | 自定义事件 | `onCustomEvent()` - 子代理运行状态 |
| `on_tool_end` | 工具调用完成 | `onLangChainEvent()` - 工具结果 |
| `end` | 流结束 | `onFinish()` - 完成回调 |

#### 事件数据结构

```json
// values 事件
{
  "event": "values",
  "data": {
    "messages": [...],
    "title": "新对话标题",
    "artifacts": [...],
    "todos": [...]
  }
}

// custom 事件 (子代理)
{
  "event": "custom",
  "data": {
    "type": "task_running",
    "task_id": "abc12345",
    "message": { "type": "ai", "content": "正在执行任务..." }
  }
}

// on_tool_end 事件
{
  "event": "on_tool_end",
  "name": "bash",
  "data": { "output": "命令执行结果..." }
}
```

---

### Step 9: 前端接收并处理事件

**文件**: `frontend/src/core/threads/hooks.ts`

```typescript
const thread = useStream<AgentThreadState>({
  client: getAPIClient(isMock),
  assistantId: "lead_agent",
  threadId: onStreamThreadId,
  reconnectOnMount: true,
  fetchStateHistory: { limit: 1 },

  // 流创建时触发
  onCreated(meta) {
    handleStreamStart(meta.thread_id);
  },

  // LangChain 事件 (工具调用)
  onLangChainEvent(event) {
    if (event.event === "on_tool_end") {
      listeners.current.onToolEnd?.({
        name: event.name,
        data: event.data,
      });
    }
  },

  // 状态更新事件
  onUpdateEvent(data) {
    const updates = Object.values(data);
    for (const update of updates) {
      // 如果包含标题更新，更新本地缓存
      if (update && "title" in update && update.title) {
        void queryClient.setQueriesData(
          { queryKey: ["threads", "search"] },
          (oldData) => oldData?.map((t) =>
            t.thread_id === threadIdRef.current
              ? { ...t, values: { ...t.values, title: update.title } }
              : t
          )
        );
      }
    }
  },

  // 自定义事件 (子代理)
  onCustomEvent(event: unknown) {
    if (typeof event === "object" && event?.type === "task_running") {
      const e = event as { type: "task_running"; task_id: string; message: AIMessage };
      updateSubtask({ id: e.task_id, latestMessage: e.message });
    }
  },

  // 流完成
  onFinish(state) {
    listeners.current.onFinish?.(state.values);
    void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
  },
});
```

---

### Step 10: UI 渲染更新

前端组件订阅 thread 状态并渲染：

```typescript
// messages: [...optimisticMessages, ...realMessages]
const mergedThread = optimisticMessages.length > 0
  ? { ...thread, messages: [...thread.messages, ...optimisticMessages] }
  : thread;

// 渲染消息列表
{mergedThread.messages.map((msg) => (
  <MessageGroup key={msg.id} message={msg} />
))}
```

---

## 🔄 特殊场景链路

### 场景 A: 需要澄清的请求

```
用户: "帮我优化代码"
         │
         ▼
┌─────────────────────────────────┐
│ LLM 分析 → 识别歧义              │
│ - 优化什么代码？                │
│ - 优化目标是什么？              │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ LLM 调用 ask_clarification 工具   │
│ question: "你想优化哪个文件？"  │
│ type: "ambiguous_requirement"   │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ ClarificationMiddleware 拦截     │
│ - 格式化问题                     │
│ - 返回 Command(goto=END)        │
│ - 中断执行，等待用户响应         │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 前端显示澄清模态框              │
│ ❓ 你想优化哪个文件？            │
│   1. src/auth.py                │
│   2. src/utils.py               │
└─────────────────────────────────┘
```

---

### 场景 B: 子代理委托 (Ultra 模式)

```
用户: "分析腾讯云股价下跌的原因"
         │
         ▼
┌─────────────────────────────────┐
│ LLM 分解任务 → 3 个子任务          │
│ 1. 财务数据分析                  │
│ 2. 负面新闻/监管                 │
│ 3. 行业趋势/竞争者              │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 并行调用 task 工具 (3 个)           │
│ - task(description="财务数据...") │
│ - task(description="负面新闻...") │
│ - task(description="行业趋势...") │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ SubagentExecutor 后台执行        │
│ - 每个子任务独立运行            │
│ - 15 分钟超时限制                  │
│ - 实时 SSE 事件推送                │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 前端接收 task_running 事件        │
│ - 显示子任务进度卡片            │
│ - 实时更新最新消息              │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 所有子任务完成 → 综合结果        │
│ "根据分析，腾讯云股价下跌主要...│
└─────────────────────────────────┘
```

---

### 场景 C: 文件上传处理

```
用户: 上传 file.pdf + "分析这个文档"
         │
         ▼
┌─────────────────────────────────┐
│ 前端：uploadFiles API           │
│ POST /api/threads/{id}/uploads │
│ - 存储文件到 /uploads           │
│ - 转换 PDF → Markdown           │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ UploadsMiddleware               │
│ - 检测新上传文件                 │
│ - 注入 <uploaded_files> 块到消息 │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ LLM 接收消息                     │
│ <uploaded_files>                │
│ - /mnt/user-data/uploads/x.pdf │
│ </uploaded_files>               │
│ 分析这个文档                     │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ LLM 调用 read_file 工具           │
│ → 读取转换后的 .md 文件           │
│ → 分析内容并回复                 │
└─────────────────────────────────┘
```

---

## 📦 数据流总结

### 请求方向

```
┌──────────────┐     ┌──────────┐     ┌───────────┐     ┌────────────┐
│   Frontend   │ ──▶ │  Nginx   │ ──▶ │ LangGraph │ ──▶ │   Agent    │
│  (Next.js)   │     │  (2026)  │     │  (2024)   │     │  Runtime   │
└──────────────┘     └──────────┘     └───────────┘     └────────────┘
```

### 响应方向 (SSE 流式)

```
┌────────────┐     ┌───────────┐     ┌──────────┐     ┌──────────────┐
│   Agent    │ ──▶ │ LangGraph │ ──▶ │  Nginx   │ ──▶ │   Frontend   │
│  Runtime   │     │  (2024)   │     │  (2026)  │     │  (Next.js)   │
└────────────┘     └───────────┘     └──────────┘     └──────────────┘
    │
    │── values 事件 (全量状态)
    │── messages-tuple (消息增量)
    │── custom 事件 (子代理)
    │── on_tool_end (工具结果)
```

---

## 🔑 关键配置对照表

| 配置项 | 前端 | 后端 |
|--------|------|------|
| **模式选择** | `context.mode` | `thinking_enabled`, `subagent_enabled` |
| **Flash** | `mode: "flash"` | `thinking_enabled: false` |
| **Pro** | `mode: "pro"` | `thinking_enabled: true`, `is_plan_mode: true` |
| **Ultra** | `mode: "ultra"` | `thinking_enabled: true`, `subagent_enabled: true`, `max_concurrent_subagents: 3` |

---

## 📝 术语表

| 术语 | 解释 |
|------|------|
| **LangGraph** | 基于 LangChain 的 Agent 编排框架，支持状态管理和流式输出 |
| **SSE** | Server-Sent Events，服务端推送技术 |
| **Middleware** | 中间件，在 LLM 调用前后执行逻辑 |
| **Checkpointer** | 状态持久化器，支持 Memory/SQLite/Postgres |
| **Subagent** | 子代理，用于并行任务分解 |
| **Tool** | 工具函数，如 bash、read_file、task 等 |
| **Thread** | 对话线程，有独立的状态和历史 |

---

*本文档详细追踪了从前端输入"你好"到后端 Agent 处理并返回响应的完整链路。*
