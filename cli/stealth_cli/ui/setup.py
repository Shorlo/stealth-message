"""First-use setup wizard (alias + passphrase → RSA-4096 keypair).

Collects alias and passphrase interactively via prompt_toolkit, generates
an RSA-4096 keypair, saves it to disk, and returns the credentials needed
to start the chat session.

Usage (called by __main__.py)::

    alias, armored_private, passphrase = await run_setup()
"""

from __future__ import annotations

import asyncio
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import ValidationError, Validator
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.text import Text

from stealth_cli import config
from stealth_cli.crypto.keys import generate_keypair, get_fingerprint

console = Console()

_STYLE = Style.from_dict(
    {
        "prompt": "bold cyan",
        "label": "ansicyan",
    }
)

# --------------------------------------------------------------------------- #
# Validators                                                                    #
# --------------------------------------------------------------------------- #


class _NonEmptyValidator(Validator):
    def __init__(self, field: str, min_len: int = 1) -> None:
        self._field = field
        self._min_len = min_len

    def validate(self, document):  # type: ignore[override]
        if len(document.text.strip()) < self._min_len:
            raise ValidationError(
                message=f"{self._field} must be at least {self._min_len} character(s)",
                cursor_position=len(document.text),
            )


class _AliasValidator(_NonEmptyValidator):
    def __init__(self) -> None:
        super().__init__("Alias", min_len=1)

    def validate(self, document):  # type: ignore[override]
        super().validate(document)
        if len(document.text.strip()) > 64:
            raise ValidationError(
                message="Alias must be 64 characters or fewer",
                cursor_position=len(document.text),
            )


class _PassphraseValidator(Validator):
    MIN_LEN = 8

    def validate(self, document):  # type: ignore[override]
        if len(document.text) < self.MIN_LEN:
            raise ValidationError(
                message=f"Passphrase must be at least {self.MIN_LEN} characters",
                cursor_position=len(document.text),
            )


# --------------------------------------------------------------------------- #
# Public entry point                                                            #
# --------------------------------------------------------------------------- #


async def run_setup() -> tuple[str, str, str]:
    """Interactive first-use wizard.

    Prompts for alias and passphrase, generates an RSA-4096 keypair,
    persists it to disk, and returns ``(alias, armored_private, passphrase)``.
    """
    _print_welcome()

    session: PromptSession[str] = PromptSession(style=_STYLE)

    alias = await _prompt_alias(session)
    passphrase = await _prompt_passphrase(session)

    armored_private, armored_public = await _generate_with_spinner(alias, passphrase)

    config.save_keypair(armored_private, armored_public, alias)

    _print_success(alias, armored_public)

    return alias, armored_private, passphrase


# --------------------------------------------------------------------------- #
# UI helpers                                                                    #
# --------------------------------------------------------------------------- #


def _print_welcome() -> None:
    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("stealth-message", "bold white"),
                "\n",
                ("End-to-end encrypted PGP chat — no server, no accounts", "dim"),
            ),
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print(
        Rule("[cyan]First-time setup[/cyan]", style="dim"),
    )
    console.print()


async def _prompt_alias(session: PromptSession[str]) -> str:
    """Prompt for a display alias (1–64 chars)."""
    console.print("[cyan]Choose a display name[/cyan] (visible to peers, max 64 chars)")
    alias: str = await session.prompt_async(
        HTML("<prompt>Alias: </prompt>"),
        validator=_AliasValidator(),
        validate_while_typing=False,
    )
    return alias.strip()


async def _prompt_passphrase(session: PromptSession[str]) -> str:
    """Prompt for passphrase with confirmation."""
    console.print()
    console.print(
        "[cyan]Choose a passphrase[/cyan] — protects your private key on disk"
    )
    console.print("[dim]Minimum 8 characters. You will be asked for it on every start.[/dim]")

    while True:
        passphrase: str = await session.prompt_async(
            HTML("<prompt>Passphrase: </prompt>"),
            is_password=True,
            validator=_PassphraseValidator(),
            validate_while_typing=False,
        )
        confirm: str = await session.prompt_async(
            HTML("<prompt>Confirm passphrase: </prompt>"),
            is_password=True,
        )
        if passphrase == confirm:
            break
        console.print("[red]Passphrases do not match. Try again.[/red]")

    return passphrase


async def _generate_with_spinner(alias: str, passphrase: str) -> tuple[str, str]:
    """Generate RSA-4096 keypair in a thread pool with a spinner."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("Generating RSA-4096 keypair…", total=None)

        loop = asyncio.get_event_loop()
        armored_private, armored_public = await loop.run_in_executor(
            None, generate_keypair, alias, passphrase
        )
        progress.remove_task(task)

    return armored_private, armored_public


def _print_success(alias: str, armored_public: str) -> None:
    fp = get_fingerprint(armored_public)

    console.print("[green]✓[/green] Keypair generated and saved.")
    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("Alias:       ", "bold"),
                (alias, "cyan"),
                "\n",
                ("Fingerprint: ", "bold"),
                (fp, "yellow"),
            ),
            title="[bold]Your identity[/bold]",
            border_style="green",
            padding=(1, 3),
        )
    )
    console.print(
        "[dim]Share your fingerprint out-of-band so peers can verify your identity.[/dim]"
    )
    console.print()
