"""Invoke tasks for the repo: run the stack, and the checks from the README.

Needs invoke on PATH - `uv tool install invoke` - then `inv --list`.
"""

from __future__ import annotations

from pathlib import Path

from invoke import Collection, Context, task

ROOT = Path(__file__).parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


# --- running it ---------------------------------------------------------------


@task(
    help={
        "host": "Bind address for the API",
        "port": "Port for the API",
        "reload": "Reload on code changes (default on)",
    }
)
def backend(c: Context, host: str = "127.0.0.1", port: int = 8000, reload: bool = True) -> None:
    """Run the FastAPI backend."""
    with c.cd(BACKEND):
        c.run(
            f"uv run hevy-coach serve --host {host} --port {port}{' --reload' if reload else ''}",
            pty=True,
        )


@task(help={"port": "Port for the dev server", "api": "Base URL of the backend to proxy to"})
def frontend(c: Context, port: int = 3000, api: str = "http://127.0.0.1:8000") -> None:
    """Run the Nuxt dev server."""
    with c.cd(FRONTEND):
        c.run(f"npm run dev -- --port {port}", pty=True, env={"NUXT_PUBLIC_API_BASE": api})


@task(
    default=True,
    help={
        "host": "Bind address for the API",
        "api-port": "Port for the API",
        "web-port": "Port for the Nuxt dev server",
    },
)
def dev(c: Context, host: str = "127.0.0.1", api_port: int = 8000, web_port: int = 3000) -> None:
    """Run backend and frontend together; Ctrl-C stops both."""
    api = f"http://{host}:{api_port}"
    # One shell, one process group: `kill 0` on exit takes both servers down.
    c.run(
        "trap 'kill 0' EXIT INT TERM; "
        f"(cd {BACKEND} && uv run hevy-coach serve --host {host} --port {api_port} --reload) & "
        f"(cd {FRONTEND} && NUXT_PUBLIC_API_BASE={api} npm run dev -- --port {web_port}) & "
        "wait",
        pty=True,
    )


# --- repo --------------------------------------------------------------------


@task
def setup(c: Context) -> None:
    """One-time setup: .env, Python deps, node deps."""
    if not (ROOT / ".env").exists():
        c.run(f"cp {ROOT / '.env.example'} {ROOT / '.env'}")
        print(".env created. The app asks for your lifter profile on first run.")
    with c.cd(BACKEND):
        c.run("uv sync")
    with c.cd(FRONTEND):
        c.run("npm install")


@task(help={"k": "Only run tests matching this expression"})
def test(c: Context, k: str | None = None) -> None:
    """Run the backend test suite."""
    with c.cd(BACKEND):
        c.run(f"uv run pytest{f' -k {k!r}' if k else ''}", pty=True)


@task(help={"fix": "Apply what ruff can fix"})
def lint(c: Context, fix: bool = False) -> None:
    """Ruff over the backend."""
    with c.cd(BACKEND):
        c.run(f"uv run ruff check{' --fix' if fix else ''} .", pty=True)


@task(aliases=["format"])
def fmt(c: Context) -> None:
    """Format the backend with ruff."""
    with c.cd(BACKEND):
        c.run("uv run ruff format .", pty=True)


@task
def typecheck(c: Context) -> None:
    """vue-tsc over the frontend."""
    with c.cd(FRONTEND):
        c.run("npm run typecheck", pty=True)


@task
def build(c: Context) -> None:
    """Production build of the frontend."""
    with c.cd(FRONTEND):
        c.run("npm run build", pty=True)


@task(pre=[lint, test, typecheck, build])
def check(c: Context) -> None:
    """Everything CI would run: lint, tests, typecheck, build."""
    print("all checks passed")


hevy_thing = Collection("hevy_thing", dev, backend, frontend)

ns = Collection(setup, test, lint, fmt, typecheck, build, check)
ns.add_collection(hevy_thing)
