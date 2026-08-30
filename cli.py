import asyncio
import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

from app.cards.service import find_card_by_name
from app.cli.menu import main as rodar_menu_interativo
from app.cli.stdio import configurar_stdio_utf8
from app.cli.tempo import cronometrar
from app.config import CARDCONJURER_DIR, PORT
from app.errors import AppError
from app.maker.service import MOLDURA_PADRAO, fill_card

configurar_stdio_utf8()

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
    ingles: bool = typer.Option(False, "--ingles", help="Aceita a carta em ingles se nao houver portugues."),
    moldura: str = typer.Option(MOLDURA_PADRAO, "--moldura", help="Valor do autoFrame do Card Conjurer."),
    sem_mtgpics: bool = typer.Option(False, "--sem-mtgpics", help="Fica na arte do Scryfall, menor."),
    arena: bool = typer.Option(False, "--arena", help="Usa a traducao do MTG Arena em vez do Scryfall, quando disponivel."),
):
    """Busca a carta pelo nome no Scryfall e preenche o Card Conjurer com ela."""

    async def _buscar_e_gerar():
        async with cronometrar(console, f"Buscando '{nome_carta}' no Scryfall"):
            carta = await find_card_by_name(nome_carta, permitir_ingles=ingles)
        if arena and not (carta.arena and carta.arena.texto):
            console.print("[yellow]Aviso:[/yellow] sem traducao de regras confiavel no Arena; seguindo sem --arena.")
        async with cronometrar(console, f"Gerando '{carta.nome_exibido}'"):
            destino = await fill_card(
                carta, moldura=moldura, arte_mtgpics=not sem_mtgpics, preferir_arena=arena
            )
        return destino

    try:
        destino = asyncio.run(_buscar_e_gerar())
    except AppError as erro:
        console.print(f"[bold red]Erro:[/bold red] {erro.message}")
        raise typer.Exit(code=1)
    console.print(f"[bold green]OK[/bold green] salvo em [bold]{destino}[/bold]")


@app.command()
def setup():
    """Baixa o fork do Card Conjurer para vendor/."""
    from app.vendor import clonar, esta_instalado, tamanho_em_disco

    if esta_instalado(CARDCONJURER_DIR):
        gb = tamanho_em_disco(CARDCONJURER_DIR) / 1024**3
        console.print(f"[bold green]OK[/bold green] ja instalado em [bold]{CARDCONJURER_DIR}[/bold] ({gb:.1f} GB)")
        return
    console.print(f"Clonando o Card Conjurer em {CARDCONJURER_DIR} - cerca de 5 GB.")
    clonar(CARDCONJURER_DIR)
    gb = tamanho_em_disco(CARDCONJURER_DIR) / 1024**3
    console.print(f"[bold green]OK[/bold green] {gb:.1f} GB em disco")


@app.command()
def serve(reload: bool = typer.Option(False, "--reload", help="Recarrega ao salvar arquivo.")):
    """Sobe a API de consulta dos dados da carta."""
    import uvicorn

    console.print(f"[bold cyan]API[/bold cyan] em http://127.0.0.1:{PORT}/docs")
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=reload)


if __name__ == "__main__":
    app()
