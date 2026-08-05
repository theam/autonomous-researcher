"""Human project CLI plus a hidden, runtime-only research protocol."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeVar
from uuid import uuid4

import typer
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from websockets.sync.client import connect as websocket_connect

from .client import HttpRuntimeClient, LocalRuntimeClient, write_snapshot
from .database import DEFAULT_DATABASE_PATH
from .engines import RuntimeEngine, runtime_engine_label
from .errors import InvariantError, LiminaError
from .runtime_cli import register_runtime_commands
from .server_cli import register_server_commands

app = typer.Typer(
    name="limina",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help=(
        "Operate durable Limina projects: provide missions and resources, review work, "
        "and steer the managed runtime."
    ),
)
project_app = typer.Typer(no_args_is_help=True, help="Create and manage Limina projects.")
resource_app = typer.Typer(no_args_is_help=True, help="Manage resources Limina may consume.")
runtime_app = typer.Typer(no_args_is_help=True, help="Administer managed runtime engines.")
runtime_codex_app = typer.Typer(no_args_is_help=True, help="Administer Codex authentication.")
database_app = typer.Typer(no_args_is_help=True)
agent_app = typer.Typer(no_args_is_help=True)
agent_hypothesis_app = typer.Typer(no_args_is_help=True)
agent_experiment_app = typer.Typer(no_args_is_help=True)
agent_finding_app = typer.Typer(no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(resource_app, name="resource")
app.add_typer(runtime_app, name="runtime")
runtime_app.add_typer(runtime_codex_app, name="codex")
app.add_typer(database_app, name="db", hidden=True)
app.add_typer(agent_app, name="_agent", hidden=True)
agent_app.add_typer(agent_hypothesis_app, name="hypothesis")
agent_app.add_typer(agent_experiment_app, name="experiment")
agent_app.add_typer(agent_finding_app, name="finding")

T = TypeVar("T")


@dataclass
class CliState:
    url: str
    database: str
    token: str | None
    admin_token: str | None
    actor: str
    as_json: bool
    no_color: bool
    _public_client: HttpRuntimeClient | None = None
    _admin_client: HttpRuntimeClient | None = None
    _agent_client: LocalRuntimeClient | HttpRuntimeClient | None = None

    @property
    def console(self) -> Console:
        return Console(no_color=self.no_color)

    @property
    def error_console(self) -> Console:
        return Console(stderr=True, no_color=self.no_color)

    def public_client(self) -> HttpRuntimeClient:
        if self._public_client is None:
            self._public_client = HttpRuntimeClient(self.url, self.token)
        return self._public_client

    def agent_client(self) -> LocalRuntimeClient | HttpRuntimeClient:
        if self._agent_client is None:
            internal_url = os.environ.get("LIMINA_INTERNAL_URL")
            internal_token = os.environ.get("LIMINA_INTERNAL_TOKEN")
            if internal_url and internal_token:
                self._agent_client = HttpRuntimeClient(
                    internal_url,
                    internal_token,
                    agent_lane=os.environ.get("LIMINA_AGENT_LANE"),
                )
            else:
                self._agent_client = LocalRuntimeClient(_database_url(self.database))
        return self._agent_client

    def admin_client(self) -> HttpRuntimeClient:
        if self._admin_client is None:
            self._admin_client = HttpRuntimeClient(self.url, self.admin_token or self.token)
        return self._admin_client

    def close(self) -> None:
        if self._public_client is not None:
            self._public_client.close()
        if self._agent_client is not None:
            self._agent_client.close()
        if self._admin_client is not None:
            self._admin_client.close()


def _state(ctx: typer.Context) -> CliState:
    return ctx.ensure_object(CliState)


def _command_id() -> str:
    return str(uuid4())


def _database_url(value: str) -> str:
    if "://" in value:
        return value
    return f"sqlite:///{Path(value).expanduser()}"


def _agent_project() -> str:
    project = os.environ.get("LIMINA_PROJECT") or os.environ.get("LIMINA_CHALLENGE")
    if not project:
        raise InvariantError(
            "The internal agent protocol requires LIMINA_PROJECT.",
            suggestion="Run this command from a Limina-managed project turn.",
        )
    return project


def _alembic_config(database_url: str) -> AlembicConfig:
    repository_root = Path(__file__).resolve().parents[2]
    source_migrations = repository_root / "migrations"
    packaged_migrations = Path(__file__).with_name("_migrations")
    script_location = source_migrations if source_migrations.is_dir() else packaged_migrations
    if not script_location.is_dir():
        raise InvariantError("Alembic migration scripts are not installed.")
    config = AlembicConfig()
    config.set_main_option("script_location", str(script_location))
    config.attributes["database_url"] = database_url
    return config


def _invoke(ctx: typer.Context, operation: Callable[[], T]) -> T:
    state = _state(ctx)
    try:
        return operation()
    except LiminaError as exc:
        value = {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
        if state.as_json:
            typer.echo(json.dumps(value, ensure_ascii=False))
        else:
            state.error_console.print(f"[bold red]{exc.code}[/bold red]  {exc.message}")
            if suggestion := exc.details.get("suggestion"):
                state.error_console.print(f"[dim]Try:[/dim] {suggestion}")
        raise typer.Exit(exc.exit_code) from None


def _emit(ctx: typer.Context, value: Any, render: Callable[[Console, Any], None]) -> None:
    state = _state(ctx)
    if state.as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        render(state.console, value)


register_runtime_commands(runtime_codex_app, _state, _invoke, _emit, _command_id)
register_server_commands(app, _state, _invoke, _emit)


def _table(console: Console, title: str, columns: list[str], rows: list[list[str]]) -> None:
    table = Table(title=title, header_style="bold cyan")
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def _render_project(console: Console, project: dict[str, Any]) -> None:
    console.print(
        Panel(
            f"[bold]{project['name']}[/bold]\n{project['mission']}\n\n"
            f"Engine     {runtime_engine_label(project['runtime'])}\n"
            f"Status     [cyan]{project['status']}[/cyan]\n"
            f"Objective  {project['current_objective']}\n"
            f"Next       {project['next_step']}\n"
            f"Blocker    {project['blocker']}",
            title=project["slug"],
            border_style="cyan",
        )
    )


@app.callback()
def root(
    ctx: typer.Context,
    url: Annotated[
        str,
        typer.Option("--url", envvar="LIMINA_URL", help="Limina instance URL."),
    ] = "http://127.0.0.1:7433",
    token: Annotated[
        str | None,
        typer.Option("--token", envvar="LIMINA_API_TOKEN", help="Instance access token."),
    ] = None,
    admin_token: Annotated[
        str | None,
        typer.Option(
            "--admin-token",
            envvar="LIMINA_ADMIN_API_TOKEN",
            help="Instance-administrator token for runtime configuration.",
        ),
    ] = None,
    actor: Annotated[
        str,
        typer.Option("--actor", envvar="LIMINA_ACTOR", help="Your team identity."),
    ] = os.environ.get("USER", "unknown"),
    database: Annotated[
        str,
        typer.Option("--database", envvar="LIMINA_DATABASE_URL", hidden=True),
    ] = str(DEFAULT_DATABASE_PATH),
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    no_color: Annotated[
        bool, typer.Option("--no-color", envvar="NO_COLOR", help="Disable ANSI styling.")
    ] = False,
) -> None:
    """Connect to one Limina instance; Limina owns all execution behind it."""
    ctx.obj = CliState(url, database, token, admin_token, actor, as_json, no_color)
    ctx.call_on_close(ctx.obj.close)


@project_app.command("create")
def create_project(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="Stable lowercase project slug.")],
    mission: Annotated[
        str | None, typer.Option("--mission", "-m", help="Mission Limina must advance.")
    ] = None,
    success: Annotated[
        str | None, typer.Option("--success", "-s", help="Observable completion criteria.")
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Human-readable name.")] = None,
    context: Annotated[
        str, typer.Option("--context", help="Known context, constraints, and prior work.")
    ] = "",
    runtime: Annotated[
        RuntimeEngine,
        typer.Option(
            "--runtime",
            help="Managed execution engine: codex or claude-code.",
        ),
    ] = "codex",
) -> None:
    """Create a project from a mission; execution begins only when you start it."""
    mission = mission or typer.prompt("Mission")
    success = success or typer.prompt("Success criteria")
    state = _state(ctx)
    result = _invoke(
        ctx,
        lambda: state.public_client().create_project(
            {
                "slug": slug,
                "name": name or slug.replace("-", " ").title(),
                "objective": mission,
                "success_criteria": success,
                "context": context,
                "runtime": runtime,
            },
            actor=state.actor,
            command_id=_command_id(),
        ),
    )
    _emit(ctx, result, _render_project)


@project_app.command("list")
def list_projects(
    ctx: typer.Context,
    all_projects: Annotated[bool, typer.Option("--all", help="Include archived projects.")] = False,
) -> None:
    """List the projects managed by this Limina instance."""
    state = _state(ctx)
    result = _invoke(ctx, lambda: state.public_client().projects(include_archived=all_projects))
    _emit(
        ctx,
        result,
        lambda console, values: _table(
            console,
            "Limina projects",
            ["Project", "Engine", "Status", "Mission", "Next"],
            [
                [
                    item["slug"],
                    runtime_engine_label(item["runtime"]),
                    item["status"],
                    item["mission"],
                    item["next_step"],
                ]
                for item in values
            ],
        ),
    )


@project_app.command("show")
def show_project(ctx: typer.Context, project: str) -> None:
    """Show one project's mission and current runtime state."""
    state = _state(ctx)
    result = _invoke(ctx, lambda: state.public_client().project(project))
    _emit(ctx, result, _render_project)


def _lifecycle(ctx: typer.Context, project: str, action: str) -> None:
    state = _state(ctx)
    result = _invoke(
        ctx,
        lambda: state.public_client().project_action(
            project, action, actor=state.actor, command_id=_command_id()
        ),
    )
    _emit(ctx, result, _render_project)


@app.command()
def start(ctx: typer.Context, project: str) -> None:
    """Start autonomous work on a created or stopped project."""
    _lifecycle(ctx, project, "start")


@app.command()
def pause(ctx: typer.Context, project: str) -> None:
    """Interrupt active work safely and leave the project resumable."""
    _lifecycle(ctx, project, "pause")


@app.command()
def resume(ctx: typer.Context, project: str) -> None:
    """Resume a paused, waiting, stopped, or failed project."""
    _lifecycle(ctx, project, "resume")


@app.command()
def stop(ctx: typer.Context, project: str) -> None:
    """Stop execution while preserving all knowledge and history."""
    _lifecycle(ctx, project, "stop")


@project_app.command("archive")
def archive_project(ctx: typer.Context, project: str) -> None:
    """Archive a project that is no longer running."""
    _lifecycle(ctx, project, "archive")


@app.command()
def status(ctx: typer.Context, project: str) -> None:
    """Show mission progress without exposing runtime machinery."""
    state = _state(ctx)
    result = _invoke(ctx, lambda: state.public_client().project_status(project))

    def render(console: Console, value: dict[str, Any]) -> None:
        _render_project(console, value["project"])
        rows = [
            [kind, state_name, str(count)]
            for kind, states in sorted(value["knowledge"].items())
            for state_name, count in sorted(states.items())
        ]
        if rows:
            _table(console, "Knowledge", ["Kind", "State", "Count"], rows)
        console.print(f"[dim]Pending team guidance:[/dim] {value['pending_guidance']}")

    _emit(ctx, result, render)


@app.command()
def review(
    ctx: typer.Context,
    project: str,
    artifact: Annotated[
        str | None, typer.Option("--artifact", "-a", help="Open one H/E/F artifact.")
    ] = None,
) -> None:
    """Review accepted work and knowledge; optionally open one artifact."""
    state = _state(ctx)
    if artifact:
        result = _invoke(ctx, lambda: state.public_client().knowledge(project, artifact.upper()))

        def render_artifact(console: Console, value: dict[str, Any]) -> None:
            console.print(
                Panel(
                    f"[bold]{value['title']}[/bold]\nStatus  {value['status']}",
                    title=value["id"],
                )
            )
            for key, content in value["content"].items():
                if content:
                    console.print(f"\n[bold]{key.replace('_', ' ').title()}[/bold]\n{content}")

        _emit(ctx, result, render_artifact)
        return

    result = _invoke(ctx, lambda: state.public_client().review(project))

    def render_review(console: Console, value: dict[str, Any]) -> None:
        _render_project(console, value["project"])
        for title, key in (
            ("Findings", "findings"),
            ("Experiments", "experiments"),
            ("Hypotheses", "hypotheses"),
        ):
            items = value[key]
            if items:
                _table(
                    console,
                    title,
                    ["ID", "Status", "Title"],
                    [[item["id"], item["status"], item["title"]] for item in items],
                )

    _emit(ctx, result, render_review)


@app.command()
def steer(
    ctx: typer.Context,
    project: str,
    message: Annotated[str, typer.Argument(help="Feedback or strategic direction.")],
    kind: Annotated[
        str,
        typer.Option("--kind", help="STEER, ANSWER, APPROVAL, COMMENT, BLOCKER, or INTERRUPT."),
    ] = "STEER",
) -> None:
    """Deliver durable guidance, live when a turn is active and queued otherwise."""
    state = _state(ctx)
    result = _invoke(
        ctx,
        lambda: state.public_client().steer_project(
            project,
            {"body": message, "kind": kind},
            actor=state.actor,
            command_id=_command_id(),
        ),
    )
    _emit(
        ctx,
        result,
        lambda console, value: console.print(
            f"[green]{value['delivery'].title()}[/green] — Limina accepted your guidance."
        ),
    )


def _render_activity(console: Console, event: dict[str, Any]) -> None:
    detail = event.get("detail", {})
    summary = detail.get("summary") or detail.get("title") or ""
    artifact = f" {event['artifact_id']}" if event.get("artifact_id") else ""
    console.print(
        f"[dim]{event['sequence']:>5} {event['created_at'][:19]}[/dim] "
        f"[cyan]{event['type']}[/cyan]{artifact} [dim]by {event['actor']}[/dim] {summary}"
    )


@app.command()
def watch(
    ctx: typer.Context,
    project: str,
    after: Annotated[int, typer.Option("--after", help="Resume after this event cursor.")] = 0,
    follow: Annotated[bool, typer.Option("--follow/--no-follow")] = True,
    interval: Annotated[float, typer.Option("--interval")] = 1.0,
) -> None:
    """Follow the durable project activity stream without entering interactive mode."""
    state = _state(ctx)
    cursor = after
    try:
        while True:
            result = _invoke(
                ctx,
                lambda cursor=cursor: state.public_client().activity(
                    project, after=cursor, limit=200
                ),
            )
            for event in result["events"]:
                if state.as_json:
                    typer.echo(json.dumps(event, ensure_ascii=False))
                else:
                    _render_activity(state.console, event)
            cursor = result["cursor"]
            if not follow:
                return
            time.sleep(max(interval, 0.1))
    except KeyboardInterrupt:
        return


@app.command()
def attach(ctx: typer.Context, project: str) -> None:
    """Enter the live project: observe Limina working and steer the active turn."""
    state = _state(ctx)
    if state.as_json:
        raise typer.BadParameter("attach is interactive and cannot be combined with --json")
    ws_url = state.url.rstrip("/")
    if ws_url.startswith("https://"):
        ws_url = "wss://" + ws_url.removeprefix("https://")
    elif ws_url.startswith("http://"):
        ws_url = "ws://" + ws_url.removeprefix("http://")
    headers = {"X-Limina-Actor": state.actor}
    if state.token:
        headers["Authorization"] = f"Bearer {state.token}"
    stop_reader = threading.Event()
    try:
        with websocket_connect(
            f"{ws_url}/v1/projects/{project}/live",
            additional_headers=headers,
            subprotocols=["limina.v1"],
        ) as socket:
            state.console.print(
                Panel(
                    "You are inside the live project. Type feedback directly.\n"
                    "Commands: /pause  /resume  /stop  /interrupt  /detach  /help",
                    title=f"Attached to {project}",
                    border_style="green",
                )
            )

            def receive() -> None:
                try:
                    for raw in socket:
                        message = json.loads(raw)
                        kind = message.get("type")
                        value = message.get("value")
                        if kind == "event":
                            _render_activity(state.console, value)
                        elif kind == "snapshot":
                            _render_project(state.console, value["project"])
                        elif kind == "delivery":
                            state.console.print(f"[green]{value.title()}[/green] guidance accepted")
                        elif kind == "state":
                            _render_project(state.console, value)
                        elif kind == "error":
                            state.error_console.print(f"[red]{value['message']}[/red]")
                except Exception as exc:
                    if not stop_reader.is_set():
                        state.error_console.print(f"[red]Live connection closed:[/red] {exc}")

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()
            while True:
                try:
                    line = input("limina> ").strip()
                except EOFError:
                    line = "/detach"
                if not line:
                    continue
                if line == "/detach":
                    break
                if line == "/help":
                    state.console.print(
                        "Type feedback, or use /pause, /resume, /stop, /interrupt, /detach."
                    )
                    continue
                if line in {"/pause", "/resume", "/stop"}:
                    socket.send(json.dumps({"type": "action", "action": line.removeprefix("/")}))
                elif line == "/interrupt":
                    socket.send(json.dumps({"type": "interrupt"}))
                else:
                    socket.send(json.dumps({"type": "steer", "body": line}))
            stop_reader.set()
    except KeyboardInterrupt:
        stop_reader.set()
    except Exception as exc:
        raise InvariantError(
            "Could not attach to the live project.", reason=str(exc), project=project
        ) from exc


@resource_app.command("variable")
def set_resource_variable(
    ctx: typer.Context,
    project: str,
    name: str,
    value: Annotated[str, typer.Argument(help="Visible value to provide to the project.")],
) -> None:
    """Set or replace a visible project variable."""
    state = _state(ctx)
    result = _invoke(
        ctx,
        lambda: state.public_client().set_variable(
            project,
            name,
            value,
            actor=state.actor,
            command_id=_command_id(),
        ),
    )
    _emit(
        ctx,
        result,
        lambda console, item: console.print(
            f"[green]Set variable[/green] {item['name']}={item['value']}"
        ),
    )


@resource_app.command("secret")
def set_resource_secret(
    ctx: typer.Context,
    project: str,
    name: str,
    from_env: Annotated[
        str | None,
        typer.Option(
            "--from-env",
            help="Read the value from this local environment variable.",
        ),
    ] = None,
    from_stdin: Annotated[
        bool,
        typer.Option("--from-stdin", help="Read the value from standard input."),
    ] = False,
) -> None:
    """Set or rotate a write-only encrypted project secret."""
    if from_env and from_stdin:
        raise typer.BadParameter("choose either --from-env or --from-stdin")
    if from_env:
        value = os.environ.get(from_env)
        if value is None:
            raise typer.BadParameter(
                f"environment variable '{from_env}' is not set",
                param_hint="--from-env",
            )
    elif from_stdin:
        value = sys.stdin.read()
        if value.endswith("\n"):
            value = value[:-1]
            if value.endswith("\r"):
                value = value[:-1]
    else:
        value = typer.prompt("Secret value", hide_input=True, confirmation_prompt=True)

    state = _state(ctx)
    result = _invoke(
        ctx,
        lambda: state.public_client().set_secret(
            project,
            name,
            value,
            actor=state.actor,
            command_id=_command_id(),
        ),
    )
    _emit(
        ctx,
        result,
        lambda console, item: console.print(
            f"[green]Stored secret[/green] {item['name']} · value hidden"
        ),
    )


@resource_app.command("list")
def list_resources(ctx: typer.Context, project: str) -> None:
    """List resources available to a project."""
    state = _state(ctx)
    result = _invoke(ctx, lambda: state.public_client().resources(project))
    _emit(
        ctx,
        result,
        lambda console, values: _table(
            console,
            "Project resources",
            ["Name", "Type", "Value"],
            [
                [
                    item["name"],
                    item["type"],
                    item["value"]
                    if item["type"] == "VARIABLE"
                    else ("configured · hidden" if item["configured"] else "unavailable"),
                ]
                for item in values
            ],
        ),
    )


@resource_app.command("remove")
def remove_resource(ctx: typer.Context, project: str, name: str) -> None:
    """Remove a project variable or secret and wipe its stored value."""
    state = _state(ctx)
    result = _invoke(
        ctx,
        lambda: state.public_client().remove_resource(
            project, name, actor=state.actor, command_id=_command_id()
        ),
    )
    _emit(
        ctx,
        result,
        lambda console, value: console.print(f"[green]Removed[/green] {value['name']}"),
    )


@app.command("export")
def export_snapshot(
    ctx: typer.Context,
    project: str,
    target: Annotated[Path, typer.Argument(help="Empty target directory.")] = Path("kb-export"),
) -> None:
    """Export a deterministic, validator-compatible Markdown knowledge base."""
    state = _state(ctx)
    files = _invoke(ctx, lambda: state.public_client().snapshot(project))
    written = _invoke(ctx, lambda: write_snapshot(files, target))
    result = {"target": str(target.resolve()), "file_count": len(written)}
    _emit(
        ctx,
        result,
        lambda console, value: console.print(
            f"[green]Exported[/green] {value['file_count']} files to {value['target']}"
        ),
    )


@database_app.command("upgrade")
def upgrade_database(ctx: typer.Context) -> None:
    state = _state(ctx)
    database_url = _database_url(state.database)
    _invoke(ctx, lambda: alembic_command.upgrade(_alembic_config(database_url), "head"))
    _emit(ctx, {"database": database_url, "revision": "head"}, lambda c, v: c.print(v))


@database_app.command("current")
def current_database_revision(ctx: typer.Context) -> None:
    state = _state(ctx)
    _invoke(
        ctx,
        lambda: alembic_command.current(
            _alembic_config(_database_url(state.database)), verbose=True
        ),
    )


def _agent_emit(ctx: typer.Context, value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False))


@agent_app.command("status")
def agent_status(ctx: typer.Context) -> None:
    state = _state(ctx)
    _agent_emit(ctx, _invoke(ctx, lambda: state.agent_client().status(_agent_project())))


@agent_app.command("list")
def agent_list(ctx: typer.Context, kind: str | None = None) -> None:
    state = _state(ctx)
    _agent_emit(ctx, _invoke(ctx, lambda: state.agent_client().artifacts(_agent_project(), kind)))


@agent_app.command("show")
def agent_show(ctx: typer.Context, artifact_id: str) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(ctx, lambda: state.agent_client().artifact(_agent_project(), artifact_id.upper())),
    )


@agent_hypothesis_app.command("add")
def agent_hypothesis_add(
    ctx: typer.Context,
    title: str,
    statement: Annotated[str, typer.Option("--statement")],
    mechanism: Annotated[str, typer.Option("--mechanism")] = "",
    generalization: Annotated[str, typer.Option("--generalization")] = "",
    shortcut_risks: Annotated[str, typer.Option("--shortcut-risks")] = "",
    test_plan: Annotated[str, typer.Option("--test-plan")] = "",
) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(
            ctx,
            lambda: state.agent_client().create_hypothesis(
                _agent_project(),
                {
                    "title": title,
                    "statement": statement,
                    "mechanism": mechanism,
                    "generalization": generalization,
                    "shortcut_risks": shortcut_risks,
                    "test_plan": test_plan,
                },
                actor=state.actor,
                command_id=_command_id(),
            ),
        ),
    )


@agent_hypothesis_app.command("decide")
def agent_hypothesis_decide(
    ctx: typer.Context,
    artifact_id: str,
    status: Annotated[str, typer.Option("--status")],
    conclusion: Annotated[str, typer.Option("--conclusion")],
    expect: Annotated[int, typer.Option("--expect")],
) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(
            ctx,
            lambda: state.agent_client().decide_hypothesis(
                _agent_project(),
                artifact_id.upper(),
                {"status": status, "conclusion": conclusion, "expected_version": expect},
                actor=state.actor,
                command_id=_command_id(),
            ),
        ),
    )


@agent_experiment_app.command("add")
def agent_experiment_add(
    ctx: typer.Context,
    hypothesis_id: str,
    title: str,
    objective: Annotated[str, typer.Option("--objective")],
    procedure: Annotated[str, typer.Option("--procedure")] = "",
    success: Annotated[str, typer.Option("--success")] = "",
    guardrails: Annotated[str, typer.Option("--guardrails")] = "",
) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(
            ctx,
            lambda: state.agent_client().create_experiment(
                _agent_project(),
                {
                    "hypothesis_id": hypothesis_id.upper(),
                    "title": title,
                    "objective": objective,
                    "procedure": procedure,
                    "success_criteria": success,
                    "guardrails": guardrails,
                },
                actor=state.actor,
                command_id=_command_id(),
            ),
        ),
    )


@agent_experiment_app.command("claim")
def agent_experiment_claim(ctx: typer.Context, artifact_id: str, ttl: int = 1800) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(
            ctx,
            lambda: state.agent_client().claim_experiment(
                _agent_project(),
                artifact_id.upper(),
                {"ttl_seconds": ttl},
                actor=state.actor,
                command_id=_command_id(),
            ),
        ),
    )


@agent_experiment_app.command("observe")
def agent_experiment_observe(
    ctx: typer.Context,
    artifact_id: str,
    observation: str,
    evidence: Annotated[str | None, typer.Option("--evidence")] = None,
) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(
            ctx,
            lambda: state.agent_client().observe_experiment(
                _agent_project(),
                artifact_id.upper(),
                {"body": observation, "evidence_ref": evidence},
                actor=state.actor,
                command_id=_command_id(),
            ),
        ),
    )


@agent_experiment_app.command("complete")
def agent_experiment_complete(
    ctx: typer.Context,
    artifact_id: str,
    results: Annotated[str, typer.Option("--results")],
    analysis: Annotated[str, typer.Option("--analysis")],
    decision: Annotated[str, typer.Option("--decision")],
    expect: Annotated[int, typer.Option("--expect")],
) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(
            ctx,
            lambda: state.agent_client().complete_experiment(
                _agent_project(),
                artifact_id.upper(),
                {
                    "results": results,
                    "analysis": analysis,
                    "decision": decision,
                    "expected_version": expect,
                },
                actor=state.actor,
                command_id=_command_id(),
            ),
        ),
    )


@agent_finding_app.command("publish")
def agent_finding_publish(
    ctx: typer.Context,
    experiment_id: str,
    title: str,
    finding: Annotated[str, typer.Option("--finding")],
    evidence: Annotated[str, typer.Option("--evidence")],
    improvement: Annotated[str, typer.Option("--improvement")] = "",
    debt: Annotated[str, typer.Option("--debt")] = "",
    next_move: Annotated[str, typer.Option("--next")] = "",
    impact: Annotated[str, typer.Option("--impact")] = "HIGH",
) -> None:
    state = _state(ctx)
    _agent_emit(
        ctx,
        _invoke(
            ctx,
            lambda: state.agent_client().publish_finding(
                _agent_project(),
                {
                    "experiment_id": experiment_id.upper(),
                    "title": title,
                    "finding": finding,
                    "evidence": evidence,
                    "improvement": improvement,
                    "remaining_debt": debt,
                    "next_move": next_move,
                    "impact": impact,
                },
                actor=state.actor,
                command_id=_command_id(),
            ),
        ),
    )


def main() -> None:
    app()
