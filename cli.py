import asyncio
import logging
import shutil
import signal
import subprocess
import sys

import typer
import uvicorn
from rich.console import Console
from rich.logging import RichHandler

from app.cards.service import find_card_by_name
from app.cli.menu import main as rodar_menu_interativo
from app.cli.stdio import configurar_stdio_utf8
from app.cli.tempo import cronometrar
from app.config import CARDCONJURER_DIR, PORT
from app.errors import AppError
from app.maker.service import fill_card
from app.qualidade import VERIFICACOES
from app.vendor import clonar, esta_instalado, patches, tamanho_em_disco

configurar_stdio_utf8()


def _matar_chromium_orfao() -> None:
    """Mata o Chromium do cache do Playwright, filtrado pelo caminho pra nao
    pegar o Chrome de verdade do usuario.

    No Windows, o Ctrl+C as vezes interrompe o asyncio antes do
    `await browser.close()` do `finally` rodar (ver app.maker.service e
    app.cli.menu), e o processo fica orfao rodando sozinho.
    """
    if sys.platform != "win32":
        return
    powershell = shutil.which("powershell")
    if powershell is None:
        return
    subprocess.run(  # noqa: S603 - comando fixo, sem entrada de fora
        [
            powershell,
            "-NoProfile",
            "-Command",
            (
                "Get-Process chrome -ErrorAction SilentlyContinue | "
                "Where-Object { $_.Path -like '*ms-playwright*' } | "
                "Stop-Process -Force"
            ),
        ],
        capture_output=True,
        check=False,
    )


def _ao_interromper(_signum, _frame):
    _matar_chromium_orfao()
    raise KeyboardInterrupt


signal.signal(signal.SIGINT, _ao_interromper)

app = typer.Typer()
console = Console()
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_time=False, show_path=False)],
)


@app.callback(invoke_without_command=True)
def principal(ctx: typer.Context):
    """Sem subcomando nenhum, abre o menu interativo. Com `fill "nome"`, gera direto sem menu."""
    if ctx.invoked_subcommand is None:
        rodar_menu_interativo()


@app.command()
def fill(
    nome_carta: str,
    ingles: bool = typer.Option(
        False, "--ingles", help="Aceita a carta em ingles se nao houver portugues."
    ),
    moldura: str | None = typer.Option(
        None,
        "--moldura",
        help="Valor do autoFrame do Card Conjurer. Sem isso, a moldura da propria impressao.",
    ),
    sem_mtgpics: bool = typer.Option(
        False, "--sem-mtgpics", help="Fica na arte do Scryfall, menor."
    ),
    arena: bool = typer.Option(
        False,
        "--arena",
        help="Usa a traducao do MTG Arena em vez do Scryfall, quando disponivel.",
    ),
):
    """Busca a carta pelo nome no Scryfall e preenche o Card Conjurer com ela."""

    async def _buscar_e_gerar():
        async with cronometrar(console, f"Buscando '{nome_carta}' no Scryfall"):
            carta = await find_card_by_name(nome_carta, permitir_ingles=ingles)
        if arena and not (carta.arena and carta.arena.texto):
            console.print(
                "[yellow]Aviso:[/yellow] sem traducao de regras confiavel no Arena; "
                "seguindo sem --arena."
            )
        async with cronometrar(console, f"Gerando '{carta.nome_exibido}'"):
            return await fill_card(
                carta, moldura=moldura, arte_mtgpics=not sem_mtgpics, preferir_arena=arena
            )

    try:
        destinos = asyncio.run(_buscar_e_gerar())
    except AppError as erro:
        console.print(f"[bold red]Erro:[/bold red] {erro.message}")
        raise typer.Exit(code=1) from erro
    for destino in destinos:
        console.print(f"[bold green]OK[/bold green] salvo em [bold]{destino}[/bold]")


@app.command()
def setup():
    """Baixa o fork do Card Conjurer para vendor/ e aplica os patches."""
    if esta_instalado(CARDCONJURER_DIR):
        gb = tamanho_em_disco(CARDCONJURER_DIR) / 1024**3
        console.print(
            f"[bold green]OK[/bold green] ja instalado em "
            f"[bold]{CARDCONJURER_DIR}[/bold] ({gb:.1f} GB)"
        )
    else:
        console.print(f"Clonando o Card Conjurer em {CARDCONJURER_DIR} - cerca de 5 GB.")
        clonar(CARDCONJURER_DIR)
        gb = tamanho_em_disco(CARDCONJURER_DIR) / 1024**3
        console.print(f"[bold green]OK[/bold green] {gb:.1f} GB em disco")

    aplicados = patches.aplicar(CARDCONJURER_DIR)
    if aplicados:
        for patch in aplicados:
            console.print(f"[bold green]OK[/bold green] patch aplicado: {patch.name}")
    else:
        console.print("[dim]Patches do Card Conjurer ja estavam aplicados.[/dim]")


@app.command()
def check(
    corrigir: bool = typer.Option(False, "--corrigir", help="Aplica o que ruff sabe arrumar."),
):
    """Roda lint, formato e tipagem - as mesmas verificacoes do portao de subida."""
    if corrigir:
        subprocess.run([sys.executable, "-m", "ruff", "check", ".", "--fix"], check=False)
        subprocess.run([sys.executable, "-m", "ruff", "format", "."], check=False)

    reprovou = False
    for nome, comando in VERIFICACOES:
        resultado = subprocess.run(  # noqa: S603 - comando fixo, sem entrada de fora
            comando, capture_output=True, text=True, check=False
        )
        if resultado.returncode == 0:
            console.print(f"[bold green]OK[/bold green] {nome}")
            continue
        reprovou = True
        console.print(f"[bold red]FALHOU[/bold red] {nome}")
        console.print(f"{resultado.stdout}{resultado.stderr}".strip())
    if reprovou:
        raise typer.Exit(code=1)


@app.command()
def serve(reload: bool = typer.Option(False, "--reload", help="Recarrega ao salvar arquivo.")):
    """Sobe a API de consulta dos dados da carta."""
    console.print(f"[bold cyan]API[/bold cyan] em http://127.0.0.1:{PORT}/docs")
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=reload)


if __name__ == "__main__":
    app()
