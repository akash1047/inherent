"""Typer entrypoint for the Inherent CLI."""

from __future__ import annotations

from typing import Annotated, Any

import click
import typer
from typer.core import TyperGroup

from inh_cli import __version__


class ExitCodeGroup(TyperGroup):
    """Reserve exit code 2 for an unavailable or unconfigured stack."""

    def main(self, *args: Any, standalone_mode: bool = True, **kwargs: Any) -> Any:
        kwargs["standalone_mode"] = False
        if not standalone_mode:
            return super().main(*args, **kwargs)
        try:
            return super().main(*args, **kwargs)
        except click.UsageError as error:
            error.show()
            raise SystemExit(1) from error
        except click.ClickException as error:
            error.show()
            raise SystemExit(error.exit_code) from error
        except click.exceptions.Exit as error:
            raise SystemExit(error.exit_code) from error


app = typer.Typer(
    cls=ExitCodeGroup,
    help="Manage and query an Inherent agent memory stack.",
    invoke_without_command=True,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    json_mode: Annotated[
        bool, typer.Option("--json", help="Write machine-readable JSON to stdout.")
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show the CLI version."),
    ] = False,
) -> None:
    """Store global output settings for subcommands."""

    del version
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode
