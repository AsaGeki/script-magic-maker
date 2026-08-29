"""Ponto de entrada do CLI.

Sem argumento abre o menu interativo; com subcomando roda direto.
"""

from pathlib import Path

import typer
from rich.console import Console

from app.cli.stdio import configurar_stdio
from app.config import settings
from app.errors import ErroDoApp, SemVersaoEmPortugues
from app.maker.browser import MOLDURA_PADRAO

configurar_stdio()

app = typer.Typer(
    help="Gera cartas de Magic: The Gathering em português, prontas pra impressão.",
    no_args_is_help=False,
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Sem subcomando, abre o menu interativo."""
    if ctx.invoked_subcommand is None:
        menu()


def menu() -> None:
    from app.cli import menu as menu_interativo

    menu_interativo()


@app.command()
def setup() -> None:
    """Baixa o fork do Card Conjurer para vendor/."""
    from app.vendor import clonar, esta_instalado, tamanho_em_disco

    destino = settings.cardconjurer_dir
    if esta_instalado(destino):
        console.print(
            f"[green]Card Conjurer já instalado[/green] em {destino} "
            f"({tamanho_em_disco(destino) / 1024**3:.1f} GB)."
        )
        return

    console.print(f"Clonando o Card Conjurer em {destino} — cerca de 2,7 GB.")
    clonar(destino)
    console.print(
        f"[green]Pronto.[/green] {tamanho_em_disco(destino) / 1024**3:.1f} GB em disco."
    )


@app.command()
def vendor(
    segundos: float = typer.Option(0, "--segundos", help="0 mantém no ar até Ctrl+C."),
) -> None:
    """Sobe o servidor local do Card Conjurer, pra abrir no navegador e conferir."""
    import time as _time

    from app.vendor import ServidorCardConjurer

    with ServidorCardConjurer() as servidor:
        console.print(f"[green]Card Conjurer em {servidor.url_do_criador}[/green]")
        if segundos:
            _time.sleep(segundos)
            return
        console.print("Ctrl+C encerra.")
        try:
            while True:
                _time.sleep(1)
        except KeyboardInterrupt:
            console.print("Encerrando.")


@app.command()
def fill(
    nome: str,
    ingles: bool = typer.Option(False, "--ingles", help="Aceita a carta em inglês se não houver português."),
    moldura: str = typer.Option(MOLDURA_PADRAO, "--moldura", help="Valor do autoFrame do Card Conjurer."),
    sem_mtgpics: bool = typer.Option(False, "--sem-mtgpics", help="Fica na arte do Scryfall, menor."),
) -> None:
    """Gera a carta de nome informado, sem passar pelo menu."""
    from app.cards import ScryfallClient
    from app.maker import Conjurer

    with ScryfallClient() as cliente:
        try:
            carta = cliente.buscar_carta(nome, permitir_ingles=ingles)
        except SemVersaoEmPortugues as erro:
            console.print(f"[yellow]{erro}[/yellow] Use --ingles pra gerar mesmo assim.")
            raise typer.Exit(code=1) from erro

    console.print(
        f"{carta.nome_exibido} — {carta.tipo_exibido} "
        f"[dim]({carta.set.upper()} #{carta.collector_number}, {carta.lang})[/dim]"
    )
    with Conjurer(moldura=moldura, arte_mtgpics=not sem_mtgpics) as conjurer:
        caminho = conjurer.gerar(carta)
        largura, altura = conjurer.dimensoes()
    console.print(f"[green]{caminho}[/green] [dim]{largura}x{altura}[/dim]")


@app.command()
def deck(
    arquivo: Path,
    ingles: bool = typer.Option(True, "--ingles/--so-portugues", help="Aceita carta em inglês quando não houver português."),
    moldura: str = typer.Option(MOLDURA_PADRAO, "--moldura", help="Valor do autoFrame do Card Conjurer."),
    pdf: bool = typer.Option(False, "--pdf", help="Monta também o PDF de impressão, com as cópias que o deck pede."),
) -> None:
    """Gera todas as cartas de uma lista de deck em texto."""
    from app.cards import ScryfallClient
    from app.deck import cartas_unicas, gerar_deck, ler_arquivo, resolver
    from app.maker import Conjurer
    from app.print import montar_pdf, repetir_por_quantidade

    entradas = cartas_unicas(ler_arquivo(arquivo))
    console.print(f"{len(entradas)} cartas distintas em {arquivo}.")

    with ScryfallClient() as cliente:
        resolvidas, falhas = resolver(entradas, cliente, permitir_ingles=ingles)
    for nome, motivo in falhas:
        console.print(f"[yellow]{nome}: {motivo}[/yellow]")
    if not resolvidas:
        console.print("[red]Nenhuma carta resolvida.[/red]")
        raise typer.Exit(code=1)

    def anunciar(indice: int, total: int, carta) -> None:
        console.print(f"[dim]{indice}/{total}[/dim] {carta.nome_exibido}")

    with Conjurer(moldura=moldura) as conjurer:
        resultado = gerar_deck(resolvidas, conjurer, ao_iniciar=anunciar)

    console.print(f"[green]{len(resultado.geradas)} imagens[/green] em {settings.output_dir}")
    if pdf and resultado.copias:
        caminho = montar_pdf(repetir_por_quantidade(resultado.copias))
        console.print(f"[green]{caminho}[/green]")
    if resultado.em_ingles:
        console.print(f"[yellow]Em inglês: {', '.join(resultado.em_ingles)}[/yellow]")
    for nome, motivo in resultado.falhas:
        console.print(f"[red]{nome}: {motivo}[/red]")


@app.command()
def pdf(
    dpi: int = typer.Option(600, "--dpi", help="Resolução da folha; 800 usa o pixel nativo da carta."),
    saida: Path = typer.Option(None, "--saida", help="Arquivo de destino."),
) -> None:
    """Monta o PDF de impressão com as cartas que já estão em output/."""
    from app.print import LayoutDaFolha, montar_pdf

    imagens = sorted(settings.output_dir.glob("*.png"))
    if not imagens:
        console.print(f"[yellow]Nenhum PNG em {settings.output_dir}.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"{len(imagens)} cartas.")
    caminho = montar_pdf(imagens, destino=saida, layout=LayoutDaFolha(dpi=dpi))
    console.print(f"[green]{caminho}[/green] [dim]{caminho.stat().st_size // 1024**2} MB[/dim]")


@app.command()
def serve(
    reload: bool = typer.Option(False, "--reload", help="Recarrega ao salvar arquivo."),
) -> None:
    """Sobe a API de consulta dos dados da carta."""
    import uvicorn

    console.print(f"[green]API em http://127.0.0.1:{settings.port}/docs[/green]")
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=reload)


@app.command()
def config() -> None:
    """Mostra a configuração em uso."""
    console.print(settings.model_dump())
    console.print(f"cardconjurer_url: {settings.cardconjurer_url}")


if __name__ == "__main__":
    try:
        app()
    except ErroDoApp as erro:
        # SystemExit, e não typer.Exit: fora do comando o Typer não trata mais nada.
        console.print(f"[red]{erro}[/red]")
        raise SystemExit(1) from erro
