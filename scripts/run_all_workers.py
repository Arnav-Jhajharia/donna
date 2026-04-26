"""Local dev: spawn all worker processes (synthesis, attention, reminders).

Production runs each as its own Railway service (set
``DONNA_PROCESS_ROLE=<role>`` per service). For local iteration it's
nicer to have one command that brings everything up.

Usage:
    python -m scripts.run_all_workers

Each worker streams to stdout with a colored prefix so you can tell
which is talking. Ctrl-C kills all three. Failures restart the
specific worker after a short backoff so a transient blip doesn't
take the whole bench down.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

WORKERS: list[tuple[str, list[str], str]] = [
    ("synth", [PYTHON, "-m", "scripts.run_synthesis_worker"], "\033[36m"),
    ("attn", [PYTHON, "-m", "scripts.run_attention_worker"], "\033[33m"),
    ("rem", [PYTHON, "-m", "scripts.run_schedule_worker"], "\033[35m"),
]
_RESET = "\033[0m"
_RESTART_BACKOFF_S = 5.0


async def _stream(label: str, color: str, stream: asyncio.StreamReader) -> None:
    while True:
        line = await stream.readline()
        if not line:
            return
        text = line.decode("utf-8", errors="replace").rstrip()
        print(f"{color}[{label:>6}]{_RESET} {text}", flush=True)


async def _supervise(label: str, cmd: list[str], color: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        env = os.environ.copy()
        # Each worker sets its own DONNA_PROCESS_ROLE so the script's
        # internal gates (and any shared init code) know which role
        # they're in. This also keeps the API gate honest if someone
        # exec's these from a shell that already had ROLE=api set.
        env.pop("DONNA_PROCESS_ROLE", None)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ROOT),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as exc:
            print(
                f"{color}[{label:>6}]{_RESET} failed to spawn: {exc}",
                file=sys.stderr,
                flush=True,
            )
            await asyncio.sleep(_RESTART_BACKOFF_S)
            continue

        assert proc.stdout is not None
        reader_task = asyncio.create_task(_stream(label, color, proc.stdout))

        stop_wait = asyncio.create_task(stop.wait())
        proc_wait = asyncio.create_task(proc.wait())
        done, pending = await asyncio.wait(
            {stop_wait, proc_wait}, return_when=asyncio.FIRST_COMPLETED
        )

        if stop_wait in done:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            for t in pending:
                t.cancel()
            await reader_task
            return

        # Process exited on its own. Drain output, then restart unless
        # we're shutting down.
        for t in pending:
            t.cancel()
        await reader_task
        rc = proc.returncode
        if stop.is_set():
            return
        print(
            f"{color}[{label:>6}]{_RESET} exited (rc={rc}); restarting in {_RESTART_BACKOFF_S:.0f}s",
            flush=True,
        )
        await asyncio.sleep(_RESTART_BACKOFF_S)


async def main() -> None:
    stop = asyncio.Event()

    def _on_signal() -> None:
        if not stop.is_set():
            print("\nshutting down workers…", flush=True)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows: signal handlers via add_signal_handler aren't
            # supported. Falling back to default Ctrl-C behavior is
            # fine here — KeyboardInterrupt propagates and the asyncio
            # tasks see CancelledError.
            pass

    await asyncio.gather(
        *(_supervise(label, cmd, color, stop) for label, cmd, color in WORKERS)
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
