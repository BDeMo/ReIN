"""Terminal CLI client for Claude Code runtime.

Connects to the server via WebSocket for streaming responses.
Also supports direct mode (no server, runs harness in-process).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

# ── Colors and formatting (no external deps) ──────────────────────

class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"


def styled(text: str, *styles: str) -> str:
    return "".join(styles) + text + Style.RESET


BANNER = f"""
{styled("╔══════════════════════════════════════════════╗", Style.CYAN)}
{styled("║", Style.CYAN)}  {styled("ReIN", Style.BOLD, Style.CYAN)}  {styled("v0.1.0", Style.DIM)}  {styled("— harness your code", Style.DIM)}     {styled("║", Style.CYAN)}
{styled("║", Style.CYAN)}  {styled("Type your message. Ctrl+C to exit.", Style.DIM)}        {styled("║", Style.CYAN)}
{styled("╚══════════════════════════════════════════════╝", Style.CYAN)}
"""


# ── WebSocket client mode ──────────────────────────────────────────

async def run_ws_client(server_url: str = "ws://localhost:8765/ws/chat", system_prompt: str | None = None):
    """Connect to server via WebSocket and run interactive chat."""
    try:
        import websockets
    except ImportError:
        print(styled("Error: websockets package required. Install: pip install websockets", Style.RED))
        return

    print(BANNER)
    print(styled(f"  Connecting to {server_url}...", Style.DIM))

    try:
        async with websockets.connect(server_url) as ws:
            print(styled("  Connected!\n", Style.GREEN))

            while True:
                # Get user input
                try:
                    user_input = input(styled("\n❯ ", Style.GREEN, Style.BOLD))
                except (EOFError, KeyboardInterrupt):
                    print(styled("\n\nGoodbye!", Style.CYAN))
                    break

                if not user_input.strip():
                    continue

                if user_input.strip().lower() in ("/exit", "/quit", "exit", "quit"):
                    print(styled("\nGoodbye!", Style.CYAN))
                    break

                # Send message
                msg: dict[str, Any] = {"type": "message", "content": user_input}
                if system_prompt:
                    msg["system_prompt"] = system_prompt
                    system_prompt = None  # Only send once

                await ws.send(json.dumps(msg))

                # Receive streaming response
                print()
                tool_active = False

                while True:
                    raw = await ws.recv()
                    event = json.loads(raw)
                    etype = event.get("type")
                    data = event.get("data", {})

                    if etype == "text_delta":
                        sys.stdout.write(data.get("text", ""))
                        sys.stdout.flush()

                    elif etype == "tool_use":
                        tool_name = data.get("name", "?")
                        tool_input = data.get("input", {})
                        input_preview = json.dumps(tool_input, ensure_ascii=False)
                        if len(input_preview) > 200:
                            input_preview = input_preview[:200] + "..."
                        print(styled(f"\n  ⚡ {tool_name}", Style.YELLOW, Style.BOLD), end="")
                        print(styled(f" {input_preview}", Style.DIM))
                        tool_active = True

                    elif etype == "tool_result":
                        result = data.get("result", "")
                        is_err = data.get("is_error", False)
                        if is_err:
                            print(styled(f"  ✗ {result[:300]}", Style.RED))
                        else:
                            preview = result[:300]
                            if len(result) > 300:
                                preview += "..."
                            print(styled(f"  ✓ {preview}", Style.DIM))
                        tool_active = False

                    elif etype == "usage":
                        inp = data.get("input_tokens", 0)
                        out = data.get("output_tokens", 0)
                        print(styled(f"\n  [{inp} in / {out} out tokens]", Style.DIM))

                    elif etype == "error":
                        print(styled(f"\n  Error: {data.get('message', '?')}", Style.RED))
                        break

                    elif etype == "turn_complete":
                        print()
                        break

    except ConnectionRefusedError:
        print(styled(f"\n  Cannot connect to {server_url}", Style.RED))
        print(styled("  Make sure the server is running: python -m src.main server", Style.DIM))
    except Exception as e:
        print(styled(f"\n  Connection error: {e}", Style.RED))


# ── Direct mode (no server) ───────────────────────────────────────

async def run_direct(
    system_prompt: str | None = None,
    project_dir: str | None = None,
    llm: Any = None,
    model_name: str | None = None,
):
    """Run the harness directly in-process (no server needed).

    Args:
        llm: Pre-built LLM provider (AnthropicProvider or LocalProvider).
             If None, builds AnthropicProvider from settings.
        model_name: Display name for the model.
    """
    from ..core.config import SettingsManager
    from ..core.harness import Harness

    print(BANNER)
    print(styled("  Running in direct mode (no server)\n", Style.DIM))

    settings_mgr = SettingsManager(project_dir)
    settings = settings_mgr.settings

    if llm is None:
        from ..llm.anthropic_llm import AnthropicProvider
        import os

        if not settings.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            print(styled("  Error: Set ANTHROPIC_API_KEY or use --local for offline mode", Style.RED))
            return

        llm = AnthropicProvider(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
        )
        model_name = model_name or settings.model

    harness = Harness(llm=llm, settings_manager=settings_mgr, project_dir=project_dir)
    await harness.initialize()

    if system_prompt:
        harness.set_system_prompt(system_prompt)

    print(styled(f"  Model: {model_name or 'unknown'}", Style.DIM))
    print(styled(f"  Tools: {', '.join(harness.tool_registry.list_names())}", Style.DIM))
    print()

    try:
        while True:
            try:
                user_input = input(styled("\n❯ ", Style.GREEN, Style.BOLD))
            except (EOFError, KeyboardInterrupt):
                print(styled("\n\nGoodbye!", Style.CYAN))
                break

            if not user_input.strip():
                continue
            if user_input.strip().lower() in ("/exit", "/quit", "exit", "quit"):
                break

            print()
            async for event in harness.run_turn(user_input):
                etype = event.type
                data = event.data

                if etype == "text_delta":
                    sys.stdout.write(data.get("text", ""))
                    sys.stdout.flush()

                elif etype == "tool_use":
                    tool_name = data.get("name", "?")
                    tool_input = data.get("input", {})
                    input_preview = json.dumps(tool_input, ensure_ascii=False)
                    if len(input_preview) > 200:
                        input_preview = input_preview[:200] + "..."
                    print(styled(f"\n  ⚡ {tool_name}", Style.YELLOW, Style.BOLD), end="")
                    print(styled(f" {input_preview}", Style.DIM))

                elif etype == "tool_result":
                    result = data.get("result", "")
                    is_err = data.get("is_error", False)
                    if is_err:
                        print(styled(f"  ✗ {result[:300]}", Style.RED))
                    else:
                        preview = result[:300]
                        if len(result) > 300:
                            preview += "..."
                        print(styled(f"  ✓ {preview}", Style.DIM))

                elif etype == "usage":
                    inp = data.get("input_tokens", 0)
                    out = data.get("output_tokens", 0)
                    print(styled(f"\n  [{inp} in / {out} out tokens]", Style.DIM))

                elif etype == "error":
                    print(styled(f"\n  Error: {data.get('message', '?')}", Style.RED))

                elif etype == "turn_complete":
                    print()

    finally:
        await harness.shutdown()
