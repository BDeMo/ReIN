# ReIN Development Conversation Log

This document records the full development journey of the ReIN project — from understanding the Claude Code architecture to implementing and publishing the runtime.

---

## Phase 1: Understanding the Codebase

### Goal
Understand the claude-code-opensource repository structure and the "harness" concept.

### Findings

**Repository Overview:**
- Claude Code is Anthropic's agentic terminal IDE
- The open-source repo (v2.1.101) contains plugins, config examples, and automation workflows
- Core runtime source code (TypeScript/Node.js) is NOT in this repo
- 13 official plugins, 12 CI/CD workflows, 584+ commits

**Harness = Runtime Control Plane:**
The harness is the event-driven infrastructure that controls what Claude can do and how:

1. **Lifecycle Hook System** — Intercepts at: UserPromptSubmit → PreToolUse → Tool Execution → PostToolUse → Stop → SessionEnd
2. **Multi-layer Permission Model** — 5 layers: managed-settings → user → project → command → hook
3. **Plugin Component System** — 5 types: commands, agents, skills, hooks, MCP
4. **Tool Execution Framework** — Built-in tools + MCP tools + Bash filtering
5. **Configuration & Policy** — strict/lax/sandbox modes, MDM deployment

**Key Plugin Examples:**
- `hookify` — User-configurable rules via `.local.md` files, rule engine with regex/contains/equals operators
- `security-guidance` — PreToolUse hook matching Edit|Write|MultiEdit, checks for XSS, SQL injection, etc.

---

## Phase 2: Architecture PPT

Created a comprehensive 11-slide PowerPoint presentation (`docs/claude-code-architecture.pptx`) in Chinese, covering the full harness architecture with deep navy/cyan theme.

---

## Phase 3: Implementation

### Design Decisions

1. **Language**: Python (available on user's system, no Node.js)
2. **Server**: FastAPI + WebSocket for streaming
3. **LLM**: Anthropic SDK with streaming tool use
4. **Architecture**: Mirror the harness pattern from Claude Code

### File Structure (26 source files)

```
src/
├── core/
│   ├── harness.py          Core orchestrator
│   ├── config.py           Multi-layer settings (managed → user → project → env)
│   └── conversation.py     Message & session management
├── llm/
│   ├── provider.py         Abstract LLM interface
│   ├── anthropic_llm.py    Anthropic Claude (streaming + tool use)
│   └── local_llm.py        Local LLM (Ollama/LM Studio/llama.cpp)
├── tools/
│   ├── registry.py         Tool registry + BaseTool
│   ├── file_tools.py       Read / Write / Edit
│   ├── bash_tool.py        Bash (command filtering + security)
│   └── search_tools.py     Grep / Glob
├── hooks/
│   ├── engine.py           Hook execution engine
│   └── types.py            9 hook event types
├── permissions/
│   └── manager.py          Multi-layer permission model
├── plugins/
│   └── loader.py           Plugin discovery & loading
├── server/
│   └── app.py              FastAPI + WebSocket streaming
├── client/
│   └── cli.py              Terminal client (WS + direct mode)
└── main.py                 Entry point
```

### Implementation Highlights

**Harness Pipeline** (`core/harness.py`):
```
User Input → UserPromptSubmit Hook → LLM Stream → Tool Call Detected
  → PreToolUse Hook → Permission Check → Tool Execute → PostToolUse Hook
  → LLM continues with result → Stop Hook
```

**LLM Providers**:
- `AnthropicProvider` — Full streaming with content_block_start/delta/stop events, JSON assembly for tool use
- `LocalProvider` — Two modes:
  - Native tool_call (for qwen2.5, llama3.1, mistral)
  - Prompt-based (injects schemas, parses ```tool_call blocks — works with ANY model)

**Tool System**:
- Read: Line numbers, offset/limit support
- Write: Create/overwrite with directory creation
- Edit: Exact string replacement, unique match validation
- Bash: Blocked patterns (rm -rf /, fork bombs), command scope filtering (Bash(git:*))
- Grep: Regex search with file type filtering
- Glob: Pattern matching sorted by mtime

**Hook Engine**:
- Command-based: sends JSON to stdin, reads JSON from stdout
- Prompt-based: LLM evaluation (placeholder for future)
- Parallel execution, first block wins
- Output format: `{hookSpecificOutput: {permissionDecision: "deny"}, systemMessage: "..."}`

**Permission Manager**:
- 5 layers resolved in order (first match wins)
- Pattern support: `Bash(git:*)`, `Edit|Write`, `mcp__*`
- Default: Read/Grep/Glob always allowed, Bash/Write/Edit require ASK

### Testing Results

All verified:
- 6 tools execute correctly
- Bash dangerous commands blocked (`rm -rf /` → Error)
- Hook engine fires events, parallel execution works
- 12 existing plugins auto-discovered (8 hooks loaded)
- Server starts, all API endpoints return correct data
- `python -m rein --help` works with all subcommands

---

## Phase 4: Offline Local LLM Support

Added `--local` flag for fully offline operation:

```bash
python -m rein direct --local --local-model qwen2.5-coder:7b
```

**LocalProvider** (`llm/local_llm.py`):
- Connects to any OpenAI-compatible server (Ollama, LM Studio, llama.cpp, vLLM)
- Auto-detects native tool_call support based on model name
- Prompt-based fallback: injects tool schemas into system prompt, parses ```tool_call JSON blocks
- Message format conversion: Anthropic ↔ OpenAI formats

---

## Phase 5: Branding & Publishing

- Named the project **ReIN** (Rein = 缰绳, harness for guiding)
- Created GitHub repo: https://github.com/BDeMo/ReIN
- Wrote comprehensive README in both English and Chinese
- MIT License

---

## Key Technical Decisions

| Decision | Why |
|----------|-----|
| Python over TypeScript | Available on user's system, faster prototyping |
| FastAPI over Flask | Native async, WebSocket, OpenAPI docs |
| Relative imports | Package works as both `python -m rein` and installed `rein` CLI |
| Dual tool-use modes | Native for capable models, prompt-based as universal fallback |
| No external tool deps | Built-in tools use only stdlib + OS calls |
| Lazy harness import | Avoids circular import between core ↔ hooks |
