from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Iterator, Literal

LangSmithEnabled = bool | Literal["local"] | None


def langsmith_available() -> bool:
    try:
        import langsmith  # noqa: F401
    except ImportError:
        return False
    return True


def traceable(*args: Any, **kwargs: Any) -> Callable:
    try:
        import langsmith as ls
    except ImportError:
        return _noop_traceable(*args, **kwargs)
    return ls.traceable(*args, **kwargs)


@contextmanager
def tracing_context(
    *,
    enabled: LangSmithEnabled = None,
    project_name: str | None = None,
    tags: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    try:
        import langsmith as ls
    except ImportError:
        with nullcontext():
            yield
        return

    with ls.tracing_context(
        enabled=enabled,
        project_name=project_name,
        tags=list(tags) or None,
        metadata=metadata,
    ):
        yield


@contextmanager
def trace_run(
    name: str,
    run_type: str = "chain",
    *,
    inputs: dict[str, Any] | None = None,
    project_name: str | None = None,
    tags: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    try:
        import langsmith as ls
    except ImportError:
        yield None
        return

    with ls.trace(
        name,
        run_type,
        inputs=inputs,
        project_name=project_name,
        tags=list(tags) or None,
        metadata=metadata,
    ) as run_tree:
        yield run_tree


def end_run(run_tree: Any | None, outputs: dict[str, Any]) -> None:
    if run_tree is not None:
        run_tree.end(outputs=outputs)


def flush() -> None:
    try:
        import langsmith as ls
    except ImportError:
        return
    try:
        ls.Client().flush()
    except Exception:
        pass


def _noop_traceable(*args: Any, **kwargs: Any) -> Callable:
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]

    def decorator(func: Callable) -> Callable:
        return func

    return decorator


@traceable(name="donna.langsmith_smoke_test", run_type="chain")
def smoke_test_payload(message: str = "langsmith smoke test") -> dict[str, str]:
    return {"status": "ok", "message": message}


def run_smoke_test(project_name: str | None = None) -> dict[str, Any]:
    metadata = {"component": "donna", "mode": "local-smoke-test"}
    with tracing_context(
        enabled="local",
        project_name=project_name or "donna-local",
        tags=("donna", "smoke-test"),
        metadata=metadata,
    ):
        with trace_run(
            "donna.langsmith_smoke_parent",
            "chain",
            inputs={"message": "langsmith smoke test"},
            project_name=project_name or "donna-local",
            tags=("donna", "smoke-test"),
            metadata=metadata,
        ) as run_tree:
            payload = smoke_test_payload()
            end_run(run_tree, {"payload": payload})
    return {
        "langsmith_available": langsmith_available(),
        "mode": "local",
        "project": project_name or "donna-local",
        "payload": payload,
    }
