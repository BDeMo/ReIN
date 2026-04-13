<p align="center">
  <h1 align="center">ReIN</h1>
  <p align="center"><em>驾驭你的代码。</em></p>
  <p align="center">
    <a href="https://pypi.org/project/rein-harness/"><img src="https://img.shields.io/pypi/v/rein-harness" alt="PyPI"></a>
    <a href="https://github.com/BDeMo/ReIN/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-blue" alt="License"></a>

  </p>
  <p align="center">
    <a href="#快速开始">快速开始</a> &middot;
    <a href="#架构">架构</a> &middot;
    <a href="#使用方式">使用方式</a> &middot;
    <a href="README.md">English</a>
  </p>
</p>

---

**ReIN** 是一个开源的智能体编程运行时，完整实现了 **harness（运行时控制平面）** 架构 —— 编排 LLM 调用、工具执行、Hook 生命周期、权限控制和插件系统的中枢。

支持 **Anthropic Claude**（云端）和 **本地 LLM**（Ollama、LM Studio、llama.cpp、vLLM）完全离线运行。

## 为什么叫 ReIN？

*Rein*（名词）—— 缰绳，驾驭马匹的工具。在软件中，它是驾驭 AI Agent 的运行时框架：**拦截**、**评估**、**执行**、**扩展** 每一个动作。

大多数智能体编程工具都是闭源黑箱。ReIN 将完整运行时开放：

- **透明可见** —— LLM 工具调用的完整编排过程
- **Hook 拦截** —— 每个生命周期事件（PreToolUse、PostToolUse、Stop 等）
- **5 层权限** —— 管理员 → 用户 → 项目 → 命令 → Hook
- **插件扩展** —— Commands、Agents、Skills、Hooks、MCP
- **完全离线** —— 搭配本地模型，无需 API Key

## 快速开始

### 前置条件

- Python 3.11+
- LLM 后端（二选一）：
  - Anthropic API Key，**或**
  - [Ollama](https://ollama.ai) / [LM Studio](https://lmstudio.ai) / 任何 OpenAI 兼容服务器

### 安装

```bash
pip install rein-harness
```

或从源码安装：

```bash
git clone https://github.com/BDeMo/ReIN.git
cd ReIN
pip install -e .
```

### 运行

```bash
# 云端模式（Anthropic Claude）
export ANTHROPIC_API_KEY=sk-ant-xxx
rein direct

# 完全离线（Ollama）
ollama pull qwen2.5-coder:7b
rein direct --local

# 自定义本地服务器
rein direct --local --local-url http://localhost:1234/v1 --local-model my-model
```

## 架构

```
rein/
├── core/
│   ├── harness.py          核心编排器 —— ReIN 的心脏
│   ├── config.py           多层设置层级
│   └── conversation.py     会话与消息管理
├── llm/
│   ├── provider.py         抽象 LLM 接口
│   ├── anthropic_llm.py    Anthropic Claude（流式 + 工具调用）
│   └── local_llm.py        本地 LLM（Ollama / LM Studio / llama.cpp / vLLM）
├── tools/
│   ├── registry.py         工具注册表与基类
│   ├── file_tools.py       Read / Write / Edit
│   ├── bash_tool.py        Bash（命令过滤 + 安全拦截）
│   └── search_tools.py     Grep / Glob
├── hooks/
│   ├── engine.py           Hook 执行引擎（命令式 + 提示式）
│   └── types.py            9 种生命周期事件
├── permissions/
│   └── manager.py          5 层权限模型（allow / deny / ask）
├── plugins/
│   └── loader.py           插件发现与加载
├── server/
│   └── app.py              FastAPI 服务器 + WebSocket 流式
├── client/
│   └── cli.py              终端客户端（Rich Markdown 渲染）
└── main.py                 CLI 入口
```

### Harness 管线

每个工具调用都通过完整的 harness 管线：

```
用户输入
  → [UserPromptSubmit Hook]      验证 / 预处理
  → LLM 流式响应                  生成文本 + 工具调用
  → 检测到工具调用
    → [PreToolUse Hook]          验证 / 修改 / 拦截
    → [权限检查]                  5 层 allow / deny / ask
    → 工具执行                    运行工具
    → [PostToolUse Hook]         响应 / 日志 / 反馈
  → LLM 继续                     将结果反馈给 LLM
  → [Stop Hook]                  验证任务完成度
```

### Hook 事件

| 事件 | 触发时机 | 用途 |
|------|---------|------|
| `PreToolUse` | 工具执行前 | 验证、修改、拦截 |
| `PostToolUse` | 工具执行后 | 响应、日志、反馈 |
| `Stop` | Agent 停止前 | 验证任务完成度 |
| `UserPromptSubmit` | 用户发送消息 | 输入预处理 |
| `SessionStart` / `SessionEnd` | 会话生命周期 | 初始化 / 清理 |
| `PreCompact` | 上下文压缩前 | 保留关键信息 |
| `Notification` | 通知 | 日志、监控 |
| `SubagentStop` | 子代理完成 | 验证子代理输出 |

### 权限层级

```
第 1 层  managed-settings.json       企业管理员（可通过 MDM 部署）
第 2 层  ~/.claude/settings.json     用户全局偏好
第 3 层  .claude/settings.json       项目级设置
第 4 层  YAML frontmatter            命令 / Agent 工具白名单
第 5 层  PreToolUse Hook             运行时动态决策
```

## 使用方式

### 直连模式（最简单）

```bash
# Anthropic Claude
rein direct

# 本地 LLM（Ollama）
rein direct --local --local-model qwen2.5-coder:7b

# 自定义系统提示
rein direct --system-prompt "你是一个 Python 专家。"
```

### 服务器 + 客户端

```bash
# 终端 1：启动服务器
rein server --port 8765

# 终端 2：连接客户端
rein client --url ws://localhost:8765/ws/chat

# 本地 LLM 服务器
rein server --local --local-model llama3.1:8b
```

### API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/tools` | GET | 列出可用工具及 schema |
| `/api/settings` | GET | 当前运行时设置 |
| `/api/chat` | POST | 非流式对话 |
| `/ws/chat` | WebSocket | 流式对话（完整 harness） |

## 本地 LLM 支持

ReIN 支持两种工具调用模式：

| 模式 | 原理 | 适用模型 |
|------|------|---------|
| **原生模式** | OpenAI `tool_call` 格式 | qwen2.5、llama3.1、mistral、functionary |
| **提示模式** | Schema 注入提示词，从输出解析 ` ```tool_call ` 块 | **任何模型** |

根据模型名自动选择。可用 `--native-tools` 强制原生模式。

### 兼容服务器

| 服务器 | 默认地址 | 安装 |
|--------|---------|------|
| [Ollama](https://ollama.ai) | `http://localhost:11434/v1` | `ollama serve` |
| [LM Studio](https://lmstudio.ai) | `http://localhost:1234/v1` | GUI 应用 |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | `http://localhost:8080/v1` | `./llama-server -m model.gguf` |
| [vLLM](https://github.com/vllm-project/vllm) | `http://localhost:8000/v1` | `vllm serve model` |
| [LocalAI](https://localai.io) | `http://localhost:8080/v1` | Docker |

### 推荐模型

| 模型 | 大小 | 工具调用 | 说明 |
|------|------|---------|------|
| `qwen2.5-coder:7b` | 4.7 GB | 原生 | 同尺寸最佳编程模型 |
| `qwen2.5-coder:1.5b` | 1.0 GB | 原生 | 轻量快速 |
| `llama3.1:8b` | 4.7 GB | 原生 | 优秀通用模型 |
| `deepseek-coder-v2:16b` | 9.0 GB | 提示 | 代码能力突出 |
| `codellama:7b` | 3.8 GB | 提示 | Meta 代码模型 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | — |
| `CLAUDE_MODEL` | 覆盖模型名 | `claude-sonnet-4-20250514` |
| `ANTHROPIC_BASE_URL` | 覆盖 API 地址 | — |
| `LOCAL_LLM_URL` | 本地服务器地址 | `http://localhost:11434/v1` |
| `LOCAL_LLM_MODEL` | 本地模型名 | `qwen2.5-coder:7b` |

## 依赖

| 包 | 用途 |
|----|------|
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | Anthropic Claude API |
| [httpx](https://github.com/encode/httpx) | 本地 LLM 异步 HTTP 客户端 |
| [fastapi](https://github.com/tiangolo/fastapi) | API 服务器框架 |
| [uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 |
| [websockets](https://github.com/python-websockets/websockets) | WebSocket 客户端 |
| [pyyaml](https://github.com/yaml/pyyaml) | YAML 解析 |
| [rich](https://github.com/Textualize/rich) | 终端富文本与 Markdown 渲染 |
| [prompt-toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) | 输入历史与编辑 |

## 致谢

ReIN 的设计灵感来自：

- **[Anthropic](https://www.anthropic.com/)** — [Claude Code](https://github.com/anthropics/claude-code) 开源插件生态与 harness 架构
- **[Ollama](https://ollama.ai/)** — 让本地 LLM 触手可及
- **[FastAPI](https://fastapi.tiangolo.com/)** — 优雅的 Python 异步 Web 框架
- **[llama.cpp](https://github.com/ggerganov/llama.cpp)** — 高效的本地模型推理
- **[OpenAI](https://openai.com/)** — Tool calling API 规范

## 许可证

[CC BY-NC-SA 4.0](LICENSE) — 非商业使用，相同方式共享。
