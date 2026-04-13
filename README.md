<p align="center">
  <h1 align="center">ReIN</h1>
  <p align="center"><em>Harness your code.</em></p>
  <p align="center">
    <a href="#quick-start">Quick Start</a> &middot;
    <a href="#architecture">Architecture</a> &middot;
    <a href="#usage">Usage</a> &middot;
    <a href="README.zh-CN.md">中文文档</a>
  </p>
</p>

---

**ReIN** is an open-source agentic coding runtime that implements a complete **harness** architecture — the control plane that orchestrates LLM calls, tool execution, hook lifecycle, permission control, and plugin systems.

It supports both **Anthropic Claude** (cloud) and **local LLMs** (Ollama, LM Studio, llama.cpp, vLLM) for fully offline operation.

## Why ReIN?

*Rein* (n.) — a strap fastened to a bit, used to guide a horse. In software, the harness that guides an AI agent: **intercepting**, **evaluating**, **executing**, and **extending** every action it takes.

Most agentic coding tools are closed-source black boxes. ReIN opens up the full runtime:

- **See exactly** how LLM tool calls are orchestrated
- **Hook into** every lifecycle event (PreToolUse, PostToolUse, Stop, etc.)
- **Control permissions** at 5 layers (admin → user → project → command → hook)
- **Extend** with plugins (commands, agents, skills, hooks, MCP)
- **Run offline** with any local model — no API key needed

## Quick Start

### Prerequisites

- Python 3.11+
- An LLM backend (choose one):
  - Anthropic API key, **or**
  - [Ollama](https://ollama.ai) / [LM Studio](https://lmstudio.ai) / any OpenAI-compatible local server

### Install

```bash
git clone https://github.com/BDeMo/ReIN.git
cd ReIN
pip install -r requirements.txt
```

### Run

```bash
# Cloud mode (Anthropic Claude)
export ANTHROPIC_API_KEY=sk-ant-xxx
python -m rein direct

# Fully offline (Ollama)
ollama pull qwen2.5-coder:7b
python -m rein direct --local

# Custom local server (LM Studio / llama.cpp / vLLM)
python -m rein direct --local --local-url http://localhost:1234/v1 --local-model my-model
```

## Architecture

```
rein/
├── core/
│   ├── harness.py          Core orchestrator — the heart of ReIN
│   ├── config.py           Multi-layer settings hierarchy
│   └── conversation.py     Session and message management
├── llm/
│   ├── provider.py         Abstract LLM interface
│   ├── anthropic_llm.py    Anthropic Claude (streaming + tool use)
│   └── local_llm.py        Local LLM (Ollama / LM Studio / llama.cpp / vLLM)
├── tools/
│   ├── registry.py         Tool registry and base class
│   ├── file_tools.py       Read / Write / Edit
│   ├── bash_tool.py        Bash with command filtering and security
│   └── search_tools.py     Grep / Glob
├── hooks/
│   ├── engine.py           Hook execution engine (command + prompt based)
│   └── types.py            9 lifecycle event types
├── permissions/
│   └── manager.py          5-layer permission model (allow / deny / ask)
├── plugins/
│   └── loader.py           Plugin discovery and loading
├── server/
│   └── app.py              FastAPI server with WebSocket streaming
├── client/
│   └── cli.py              Terminal client (direct + server modes)
└── main.py                 CLI entry point
```

### Harness Pipeline

Every tool call passes through the full harness pipeline:

```
User Input
  → [UserPromptSubmit Hook]      Validate / preprocess
  → LLM streaming response       Generate text + tool calls
  → Tool call detected
    → [PreToolUse Hook]          Validate / modify / block
    → [Permission Check]         5-layer allow / deny / ask
    → Tool Execution             Run the tool
    → [PostToolUse Hook]         React / log / feedback
  → LLM continues                Feed result back
  → [Stop Hook]                  Validate task completion
```

### Hook Events

| Event | When | Purpose |
|-------|------|---------|
| `PreToolUse` | Before tool execution | Validate, modify, or block |
| `PostToolUse` | After tool execution | React, log, feedback |
| `Stop` | Before agent stops | Verify task completion |
| `UserPromptSubmit` | User sends message | Input preprocessing |
| `SessionStart` / `SessionEnd` | Session lifecycle | Init / cleanup |
| `PreCompact` | Before context compaction | Preserve critical info |
| `Notification` | Any notification | Logging, monitoring |
| `SubagentStop` | Subagent completes | Validate subagent output |

### Permission Layers

```
Layer 1  managed-settings.json       Enterprise admin (MDM deployable)
Layer 2  ~/.claude/settings.json     User global preferences
Layer 3  .claude/settings.json       Project-level settings
Layer 4  YAML frontmatter            Command / Agent tool whitelist
Layer 5  PreToolUse Hook             Runtime dynamic decisions
```

## Usage

### Direct Mode (simplest)

```bash
# Anthropic Claude
python -m rein direct

# Local LLM (Ollama)
python -m rein direct --local --local-model qwen2.5-coder:7b

# Custom system prompt
python -m rein direct --system-prompt "You are a Python expert."
```

### Server + Client

```bash
# Terminal 1: server
python -m rein server --port 8765

# Terminal 2: client
python -m rein client --url ws://localhost:8765/ws/chat

# Local LLM server
python -m rein server --local --local-model llama3.1:8b
```

### API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/tools` | GET | List tools with schemas |
| `/api/settings` | GET | Current settings |
| `/api/chat` | POST | Non-streaming chat |
| `/ws/chat` | WebSocket | Streaming chat (full harness) |

### WebSocket Protocol

```jsonc
// Client → Server
{"type": "message", "content": "Read main.py", "system_prompt": "..."}

// Server → Client (streamed)
{"type": "text_delta",    "data": {"text": "I'll read..."}}
{"type": "tool_use",      "data": {"id": "...", "name": "Read", "input": {...}}}
{"type": "tool_result",   "data": {"tool_use_id": "...", "result": "..."}}
{"type": "usage",         "data": {"input_tokens": 150, "output_tokens": 80}}
{"type": "turn_complete", "data": {"stop_reason": "end_turn"}}
```

## Local LLM

ReIN supports two tool-use modes:

| Mode | How | Models |
|------|-----|--------|
| **Native** | OpenAI `tool_call` format | qwen2.5, llama3.1, mistral, functionary |
| **Prompt-based** | Schemas in prompt, parses ` ```tool_call ` blocks | **Any model** |

Auto-detected from model name. Force native with `--native-tools`.

### Compatible Servers

| Server | Default URL | Install |
|--------|------------|---------|
| [Ollama](https://ollama.ai) | `http://localhost:11434/v1` | `ollama serve` |
| [LM Studio](https://lmstudio.ai) | `http://localhost:1234/v1` | GUI |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | `http://localhost:8080/v1` | `./llama-server -m model.gguf` |
| [vLLM](https://github.com/vllm-project/vllm) | `http://localhost:8000/v1` | `vllm serve model` |
| [LocalAI](https://localai.io) | `http://localhost:8080/v1` | Docker |

### Recommended Models

| Model | Size | Tool Use | Notes |
|-------|------|----------|-------|
| `qwen2.5-coder:7b` | 4.7 GB | Native | Best coding model at this size |
| `qwen2.5-coder:1.5b` | 1.0 GB | Native | Fast, lightweight |
| `llama3.1:8b` | 4.7 GB | Native | Strong general purpose |
| `deepseek-coder-v2:16b` | 9.0 GB | Prompt | Excellent at code |
| `codellama:7b` | 3.8 GB | Prompt | Meta's code model |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `CLAUDE_MODEL` | Override model name | `claude-sonnet-4-20250514` |
| `ANTHROPIC_BASE_URL` | Override API URL | — |
| `LOCAL_LLM_URL` | Local server URL | `http://localhost:11434/v1` |
| `LOCAL_LLM_MODEL` | Local model name | `qwen2.5-coder:7b` |

## Dependencies

| Package | Purpose |
|---------|---------|
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | Anthropic Claude API |
| [httpx](https://github.com/encode/httpx) | Async HTTP for local LLMs |
| [fastapi](https://github.com/tiangolo/fastapi) | API server |
| [uvicorn](https://github.com/encode/uvicorn) | ASGI server |
| [websockets](https://github.com/python-websockets/websockets) | WebSocket client |
| [pyyaml](https://github.com/yaml/pyyaml) | YAML parsing |

## Acknowledgements

ReIN is inspired by and built upon ideas from:

- **[Anthropic](https://www.anthropic.com/)** — the [Claude Code](https://github.com/anthropics/claude-code) open-source plugin ecosystem and harness architecture
- **[Ollama](https://ollama.ai/)** — making local LLMs accessible to everyone
- **[FastAPI](https://fastapi.tiangolo.com/)** — elegant async Python web framework
- **[llama.cpp](https://github.com/ggerganov/llama.cpp)** — efficient local model inference
- **[OpenAI](https://openai.com/)** — the tool-calling API convention adopted by local LLM servers

## License

[MIT](LICENSE)
