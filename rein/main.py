"""ReIN — harness your code.

Usage:
  python -m rein server  [--host HOST] [--port PORT]        API server (Anthropic)
  python -m rein server  --local --local-model MODEL        API server (local LLM)
  python -m rein client  [--url URL]                        CLI client → server
  python -m rein direct                                     Direct mode (Anthropic)
  python -m rein direct  --local                            Direct mode (local, fully offline)
  python -m rein                                            Same as 'direct'

Environment:
  ANTHROPIC_API_KEY    — Required for Anthropic mode
  CLAUDE_MODEL         — Override model name
  LOCAL_LLM_URL        — Local server URL (default: http://localhost:11434/v1)
  LOCAL_LLM_MODEL      — Local model name (default: qwen2.5-coder:7b)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

DEFAULT_SYSTEM_PROMPT = """\
You are an AI coding assistant running inside an agentic coding environment. \
You have access to tools for reading/writing files, running bash commands, and searching code. \
Use these tools to help the user with software engineering tasks. \
Be concise and direct. Execute code changes rather than just describing them."""


def main():
    parser = argparse.ArgumentParser(
        description="ReIN — harness your code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # ── Shared local-LLM flags ─────────────────────────────────────
    def add_local_flags(p):
        p.add_argument("--local", action="store_true",
                        help="Use local LLM (Ollama/LM Studio/llama.cpp) instead of Anthropic")
        p.add_argument("--local-url", default=None,
                        help="Local LLM server URL (default: http://localhost:11434/v1)")
        p.add_argument("--local-model", default=None,
                        help="Local model name (default: qwen2.5-coder:7b)")
        p.add_argument("--native-tools", action="store_true", default=False,
                        help="Force native tool_call mode (vs prompt-based)")

    # server
    srv = sub.add_parser("server", help="Start the API server")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8765)
    srv.add_argument("--project-dir", default=None)
    srv.add_argument("--log-level", default="INFO")
    add_local_flags(srv)

    # client
    cli = sub.add_parser("client", help="Connect to a running server")
    cli.add_argument("--url", default="ws://localhost:8765/ws/chat")
    cli.add_argument("--system-prompt", default=None)

    # direct
    drt = sub.add_parser("direct", help="Run directly (no server)")
    drt.add_argument("--project-dir", default=None)
    drt.add_argument("--system-prompt", default=None)
    drt.add_argument("--log-level", default="INFO")
    add_local_flags(drt)

    args = parser.parse_args()

    if args.command == "server":
        _run_server(args)
    elif args.command == "client":
        _run_client(args)
    elif args.command == "direct":
        _run_direct(args)
    else:
        # Default: direct mode
        args.project_dir = None
        args.system_prompt = None
        args.log_level = "INFO"
        args.local = False
        args.local_url = None
        args.local_model = None
        args.native_tools = False
        _run_direct(args)


def _build_llm(args):
    """Build the appropriate LLM provider from CLI args."""
    if getattr(args, "local", False):
        from .llm.local_llm import LocalProvider

        url = args.local_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")
        model = args.local_model or os.environ.get("LOCAL_LLM_MODEL", "qwen2.5-coder:7b")
        native = True if args.native_tools else None
        return LocalProvider(base_url=url, model=model, native_tool_use=native), model
    else:
        from .llm.anthropic_llm import AnthropicProvider
        from .core.config import SettingsManager

        sm = SettingsManager(getattr(args, "project_dir", None))
        s = sm.settings
        return AnthropicProvider(
            api_key=s.api_key, base_url=s.base_url, model=s.model
        ), s.model


def _run_server(args):
    _setup_logging(args.log_level)

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn required. Install: pip install uvicorn")
        sys.exit(1)

    from .server.app import create_app

    app = create_app(
        project_dir=args.project_dir,
        local=getattr(args, "local", False),
        local_url=getattr(args, "local_url", None),
        local_model=getattr(args, "local_model", None),
        native_tools=getattr(args, "native_tools", False),
    )

    mode = "LOCAL" if args.local else "ANTHROPIC"
    print(f"\n  ReIN Server [{mode}]")
    print(f"  http://{args.host}:{args.port}")
    print(f"  WebSocket: ws://{args.host}:{args.port}/ws/chat")
    if args.local:
        url = args.local_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")
        model = args.local_model or os.environ.get("LOCAL_LLM_MODEL", "qwen2.5-coder:7b")
        print(f"  LLM: {model} @ {url}")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


def _run_client(args):
    from .client.cli import run_ws_client
    asyncio.run(run_ws_client(server_url=args.url, system_prompt=args.system_prompt))


def _run_direct(args):
    _setup_logging(args.log_level)
    from .client.cli import run_direct

    prompt = args.system_prompt or DEFAULT_SYSTEM_PROMPT
    llm, model_name = _build_llm(args)
    asyncio.run(run_direct(
        system_prompt=prompt,
        project_dir=args.project_dir,
        llm=llm,
        model_name=model_name,
    ))


def _setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


if __name__ == "__main__":
    main()
