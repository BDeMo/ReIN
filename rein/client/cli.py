"""Terminal CLI client for ReIN.

Provides an interactive chatbot experience with:
  - Rich Markdown rendering for assistant responses
  - Colored tool call display
  - Prompt toolkit input with history
  - WebSocket streaming (client mode) and direct in-process mode
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

VERSION = "0.1.0"


def _print_banner(mode: str = "direct", model: str = "", tools: list[str] | None = None):
    banner = Text()
    banner.append("  ReIN", style="bold cyan")
    banner.append(f"  v{VERSION}", style="dim")
    banner.append("  — harness your code", style="dim")

    console.print()
    console.print(Panel(banner, border_style="cyan", padding=(0, 1)))
    console.print(f"  [dim]Mode: {mode}[/dim]")
    if model:
        console.print(f"  [dim]Model: {model}[/dim]")
    if tools:
        console.print(f"  [dim]Tools: {', '.join(tools)}[/dim]")
    console.print(f"  [dim]Type /exit to quit. Ctrl+C to interrupt.[/dim]")
    console.print()


def _get_input() -> str | None:
    """Get user input with prompt_toolkit if available, fallback to input()."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory

        if not hasattr(_get_input, "_session"):
            _get_input._session = PromptSession(history=InMemoryHistory())

        return _get_input._session.prompt("❯ ")
    except ImportError:
        return input("❯ ")
    except (EOFError, KeyboardInterrupt):
        return None


def _render_text(text: str):
    """Render assistant text as Markdown."""
    if text.strip():
        console.print()
        console.print(Markdown(text))


def _render_tool_use(name: str, tool_input: dict):
    """Show tool call."""
    preview = json.dumps(tool_input, ensure_ascii=False)
    if len(preview) > 200:
        preview = preview[:200] + "..."
    console.print(f"\n  [bold yellow]⚡ {name}[/bold yellow] [dim]{preview}[/dim]")


def _render_tool_result(result: str, is_error: bool = False):
    """Show tool result."""
    preview = result[:300]
    if len(result) > 300:
        preview += "..."
    if is_error:
        console.print(f"  [red]✗ {preview}[/red]")
    else:
        console.print(f"  [dim]✓ {preview}[/dim]")


def _render_usage(input_tokens: int, output_tokens: int):
    console.print(f"\n  [dim][{input_tokens} in / {output_tokens} out tokens][/dim]")


# ── WebSocket client mode ──────────────────────────────────────────

async def run_ws_client(
    server_url: str = "ws://localhost:8765/ws/chat",
    system_prompt: str | None = None,
):
    """Connect to server via WebSocket and run interactive chat."""
    try:
        import websockets
    except ImportError:
        console.print("[red]Error: websockets package required. Install: pip install websockets[/red]")
        return

    _print_banner(mode="client", model=f"→ {server_url}")
    console.print(f"  [dim]Connecting to {server_url}...[/dim]")

    try:
        async with websockets.connect(server_url) as ws:
            console.print("  [green]Connected![/green]\n")

            while True:
                user_input = _get_input()
                if user_input is None:
                    console.print("\n[cyan]Goodbye![/cyan]")
                    break

                if not user_input.strip():
                    continue
                if user_input.strip().lower() in ("/exit", "/quit", "exit", "quit"):
                    console.print("[cyan]Goodbye![/cyan]")
                    break

                msg: dict[str, Any] = {"type": "message", "content": user_input}
                if system_prompt:
                    msg["system_prompt"] = system_prompt
                    system_prompt = None

                await ws.send(json.dumps(msg))

                # Collect streaming response
                text_buffer = ""

                while True:
                    raw = await ws.recv()
                    event = json.loads(raw)
                    etype = event.get("type")
                    data = event.get("data", {})

                    if etype == "text_delta":
                        text_buffer += data.get("text", "")

                    elif etype == "tool_use":
                        # Flush text before tool display
                        if text_buffer:
                            _render_text(text_buffer)
                            text_buffer = ""
                        _render_tool_use(data.get("name", "?"), data.get("input", {}))

                    elif etype == "tool_result":
                        _render_tool_result(
                            data.get("result", ""),
                            data.get("is_error", False),
                        )

                    elif etype == "usage":
                        _render_usage(
                            data.get("input_tokens", 0),
                            data.get("output_tokens", 0),
                        )

                    elif etype == "error":
                        if text_buffer:
                            _render_text(text_buffer)
                            text_buffer = ""
                        console.print(f"\n  [red]Error: {data.get('message', '?')}[/red]")
                        break

                    elif etype == "turn_complete":
                        if text_buffer:
                            _render_text(text_buffer)
                            text_buffer = ""
                        console.print()
                        break

    except ConnectionRefusedError:
        console.print(f"\n  [red]Cannot connect to {server_url}[/red]")
        console.print("  [dim]Start the server first: rein server[/dim]")
    except Exception as e:
        console.print(f"\n  [red]Connection error: {e}[/red]")


# ── Direct mode (no server) ───────────────────────────────────────

async def run_direct(
    system_prompt: str | None = None,
    project_dir: str | None = None,
    llm: Any = None,
    model_name: str | None = None,
):
    """Run the harness directly in-process (no server needed)."""
    from ..core.config import SettingsManager
    from ..core.harness import Harness

    settings_mgr = SettingsManager(project_dir)
    settings = settings_mgr.settings

    if llm is None:
        from ..llm.anthropic_llm import AnthropicProvider

        if not settings.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            console.print("[red]Error: Set ANTHROPIC_API_KEY or use --local for offline mode[/red]")
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

    _print_banner(
        mode="direct",
        model=model_name or "unknown",
        tools=harness.tool_registry.list_names(),
    )

    try:
        while True:
            user_input = _get_input()
            if user_input is None:
                console.print("\n[cyan]Goodbye![/cyan]")
                break

            if not user_input.strip():
                continue
            if user_input.strip().lower() in ("/exit", "/quit", "exit", "quit"):
                console.print("[cyan]Goodbye![/cyan]")
                break

            # Collect streaming response
            text_buffer = ""

            async for event in harness.run_turn(user_input):
                etype = event.type
                data = event.data

                if etype == "text_delta":
                    text_buffer += data.get("text", "")

                elif etype == "tool_use":
                    if text_buffer:
                        _render_text(text_buffer)
                        text_buffer = ""
                    _render_tool_use(data.get("name", "?"), data.get("input", {}))

                elif etype == "tool_result":
                    _render_tool_result(
                        data.get("result", ""),
                        data.get("is_error", False),
                    )

                elif etype == "usage":
                    _render_usage(
                        data.get("input_tokens", 0),
                        data.get("output_tokens", 0),
                    )

                elif etype == "error":
                    if text_buffer:
                        _render_text(text_buffer)
                        text_buffer = ""
                    console.print(f"\n  [red]Error: {data.get('message', '?')}[/red]")

                elif etype == "turn_complete":
                    if text_buffer:
                        _render_text(text_buffer)
                        text_buffer = ""
                    console.print()

    finally:
        await harness.shutdown()
