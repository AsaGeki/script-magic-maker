"""Menu interativo do CLI (banner + navegacao por seta via questionary) -
alternativa ao modo direto `cli.py fill "nome"` pra quem quer explorar sem
decorar flag nenhuma. 3 categorias: Cartas (avulsa), Decks (lista inteira) e
PDF (folha de impressao).

Todo prompt usa `ask_async()`, nunca `ask()` (sincrono) - o menu roda dentro
de 1 `asyncio.run()` so, ver main().
"""

import asyncio
from pathlib import Path

import pyfiglet
import questionary
from playwright.async_api import Browser, async_playwright
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.cards.models import ScryfallCard
from app.cards.service import (
    ULTIMA_EDICAO_EM_PORTUGUES,
    find_cards_by_set,
    list_sets,
    search_cards,
    search_cards_by_term,
    suggest_names,
)
from app.cli.preview import escolher_impressao, mostrar_ficha
from app.cli.stdio import configurar_stdio_utf8
from app.cli.tempo import cronometrar
from app.config import CARDCONJURER_URL, HEADLESS, OUTPUT_DIR
from app.deck.service import buscar_cartas_do_deck
from app.deck.texto import cartas_unicas, ler_arquivo
from app.errors import AppError
from app.maker.service import MOLDURAS, MOLDURA_PADRAO, fill_card, moldura_sugerida
from app.print import layout
from app.print import pdf as print_pdf
from app.print.service import montar_lote, repetir_por_copias
from app.slug import slug
from app.vendor.server import ServidorCardConjurer

console = Console()

CATEGORIA_CARTAS = "Cartas"
CATEGORIA_DECKS = "Decks"
CATEGORIA_IMPRIMIR = "PDF"
OPCAO_SAIR = "Sair"
VOLTAR = "Voltar"

# Estrutura padrao de output/: cartas avulsas em cards/ (default de fill_card,
# ver PASTA_CARTAS_AVULSAS em app.maker.service); cada deck monta a propria
# subpasta dentro de DECKS_DIR.
DECKS_DIR = Path(OUTPUT_DIR) / "decks"


def mostrar_banner() -> None:
    console.print(
        f"[bold cyan]{pyfiglet.figlet_format('Magic Maker', font='slant')}[/]"
    )


def _mostrar_tabela(cartas: list[ScryfallCard]) -> None:
    tabela = Table(title=f"Cartas ({len(cartas)})")
    tabela.add_column("Nome")
    tabela.add_column("Tipo")
    tabela.add_column("Edicao")
    tabela.add_column("PT")
    for carta in cartas:
        pt = "[green]sim[/]" if carta.traduzida else "[red]nao[/]"
        tabela.add_row(
            carta.nome_exibido,
            carta.tipo_exibido or "-",
            f"{carta.set.upper()} #{carta.collector_number}",
            pt,
        )
    console.print(tabela)


def _preferir_arena_por_padrao(carta: ScryfallCard) -> bool:
    """No lote, so troca pro texto do Arena quando a carta nao tem portugues
    NENHUM no Scryfall e o Arena tem regra confiavel (ver app.cards.arena) -
    preenche so o buraco do corte de traducao, sem pisar em texto que ja
    saiu impresso oficialmente (esse pode so ter mudado por errata, e o
    objetivo aqui e reproduzir o que foi impresso)."""
    return not carta.traduzida and bool(carta.arena and carta.arena.texto)


async def _gerar_uma(
    carta: ScryfallCard,
    *,
    browser: Browser | None = None,
    confirmar: bool = True,
    pasta_destino: Path | None = None,
    moldura: str | None = None,
    preferir_arena: bool | None = None,
) -> Path | None:
    """No lote (`confirmar=False`), a selecao no checkbox ja e a confirmacao.
    `pasta_destino` None cai no padrao de fill_card (output/cards).
    `preferir_arena` None deixa _preferir_arena_por_padrao decidir por carta."""
    if preferir_arena is None:
        preferir_arena = _preferir_arena_por_padrao(carta)
    if not carta.traduzida:
        se_arena = "usando traducao do MTG Arena (nao impressa)" if preferir_arena else "vai sair em ingles"
        cor = "magenta" if preferir_arena else "red"
        console.print(f'  [{cor}]![/] "{carta.nome_exibido}" sem impressao PT - {se_arena}')
    if (
        confirmar
        and not await questionary.confirm(
            f'Gerar "{carta.nome_exibido}"?', default=True
        ).ask_async()
    ):
        return None
    async with cronometrar(console, f'  Gerando "{carta.nome_exibido}"'):
        destino = await fill_card(
            carta,
            browser=browser,
            pasta_destino=pasta_destino,
            moldura=moldura,
            preferir_arena=preferir_arena,
        )
    console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")
    return destino


async def _gerar_varias(
    cartas: list[ScryfallCard],
    *,
    pasta_destino: Path | None = None,
    moldura: str | None = None,
    preferir_arena: bool | None = None,
) -> list[tuple[Path, int]]:
    """Abre 1 Chromium so e reusa pra todas as cartas do lote - abrir/fechar 1
    browser por carta era o gargalo de velocidade gerando varias de uma vez.

    Retorna (caminho, copias) de cada carta gerada, pro PDF saber quantas vezes
    repetir cada uma na folha."""
    geradas: list[tuple[Path, int]] = []
    servidor = ServidorCardConjurer().start()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        try:
            for indice, carta in enumerate(cartas, start=1):
                console.rule(f"{indice}/{len(cartas)}: {carta.nome_exibido}")
                try:
                    destino = await _gerar_uma(
                        carta,
                        browser=browser,
                        confirmar=False,
                        pasta_destino=pasta_destino,
                        moldura=moldura,
                        preferir_arena=preferir_arena,
                    )
                except AppError as erro:
                    console.print(f"  [red]![/] {erro.message}")
                    continue
                if destino is not None:
                    geradas.append((destino, carta.copias))
        finally:
            await browser.close()
            servidor.stop()
    return geradas


NOME_DA_MOLDURA = {valor: nome for nome, valor in MOLDURAS.items()}


async def _confirmar_moldura(carta: ScryfallCard) -> str | None:
    """Detecta a moldura pela impressao real (ver moldura_sugerida) e so
    pergunta se o usuario quiser trocar - a deteccao acerta a maioria, entao
    perguntar sempre seria fricao a toa."""
    sugerida = moldura_sugerida(carta)
    console.print(f"  Moldura: [bold]{NOME_DA_MOLDURA.get(sugerida, sugerida)}[/]")
    if not await questionary.confirm("Trocar a moldura?", default=False).ask_async():
        return sugerida
    escolha = await questionary.select(
        "Qual moldura?", choices=[*MOLDURAS, VOLTAR]
    ).ask_async()
    if escolha is None or escolha == VOLTAR:
        return sugerida
    return MOLDURAS[escolha]


async def _escolher_e_gerar(
    cartas: list[ScryfallCard],
    *,
    pre_marcadas: bool = False,
    pasta_destino: Path | None = None,
) -> list[tuple[Path, int]]:
    """Mostra a tabela de resultado + checkbox de selecao multipla - usado por
    todo fluxo que termina numa lista de cartas candidatas (busca por termo,
    edicao, deck importado). Cada carta usa a moldura detectada pela propria
    impressao (ver moldura_sugerida), sem perguntar 1 vez so pra todas."""
    if not cartas:
        console.print("  [red]![/] Nenhuma carta encontrada.")
        return []
    _mostrar_tabela(cartas)
    sufixo = " (ja vem todas marcadas)" if pre_marcadas else ""
    escolhidas = await questionary.checkbox(
        f"Selecione quais gerar{sufixo}:",
        choices=[
            questionary.Choice(
                f"{carta.nome_exibido} ({carta.set.upper()} #{carta.collector_number})",
                carta,
                checked=pre_marcadas,
            )
            for carta in cartas
        ],
    ).ask_async()
    if not escolhidas:
        return []
    return await _gerar_varias(escolhidas, pasta_destino=pasta_destino)


# --- Fluxos de Cartas ------------------------------------------------------


async def _fluxo_carta_por_nome() -> None:
    procurado = await questionary.text("Nome da carta (portugues ou ingles):").ask_async()
    if not procurado:
        return

    async with cronometrar(console, "Buscando no Scryfall"):
        impressoes = await search_cards(procurado.strip())
        if not impressoes:
            impressoes = await search_cards(procurado.strip(), lang="en")
        if not impressoes:
            nomes = await suggest_names(procurado.strip())
    if not impressoes:
        if not nomes:
            console.print(f'  [red]![/] Nada encontrado para "{procurado}".')
            return
        escolhido = await questionary.select("Qual delas?", choices=[*nomes, VOLTAR]).ask_async()
        if escolhido is None or escolhido == VOLTAR:
            return
        async with cronometrar(console, "Buscando no Scryfall"):
            impressoes = await search_cards(escolhido) or await search_cards(escolhido, lang="en")

    carta = await escolher_impressao(impressoes)
    mostrar_ficha(carta)
    preferir_arena = False
    if carta.arena and carta.arena.texto:
        preferir_arena = await questionary.confirm(
            "Usar o texto do MTG Arena (painel acima) em vez do oficial impresso?",
            default=_preferir_arena_por_padrao(carta),
        ).ask_async()
    moldura = await _confirmar_moldura(carta)
    await _gerar_varias([carta], moldura=moldura, preferir_arena=preferir_arena)


async def _fluxo_carta_por_termo() -> None:
    termo = await questionary.text("Termo que aparece no nome:").ask_async()
    if not termo:
        return
    async with cronometrar(console, "Buscando no Scryfall"):
        cartas = await search_cards_by_term(termo.strip())
    await _escolher_e_gerar(cartas)


async def _fluxo_carta_por_edicao() -> None:
    """So lista edicao que pode ter carta em portugues (ver list_sets); quem
    quiser as de depois do corte de traducao escolhe a opcao de ver todas."""
    todas = False
    while True:
        async with cronometrar(console, "Verificando quais edições têm português"):
            edicoes = await list_sets(limite=24, so_com_portugues=not todas)
        opcoes = [
            questionary.Choice(
                f"{e['name']} ({e['code'].upper()}) - {e['released_at'][:4]}, "
                f"{e['card_count']} cartas",
                e,
            )
            for e in edicoes
        ]
        alternar = (
            "So as que tem portugues" if todas else "Ver tambem as sem portugues"
        )
        escolha = await questionary.select(
            "Qual edicao?", choices=[*opcoes, alternar, VOLTAR]
        ).ask_async()

        if escolha is None or escolha == VOLTAR:
            return
        if escolha == alternar:
            todas = not todas
            continue
        break

    codigo = escolha["code"]
    async with cronometrar(console, f"Buscando cartas de {codigo.upper()}"):
        cartas = await find_cards_by_set(codigo)
    if not cartas:
        # Depois do corte, a causa e sempre a mesma; antes dele, costuma ser
        # colecao de promo ou especial, que a Wizards nao traduzia.
        motivo = (
            " - a Wizards parou de traduzir depois de Modern Horizons 3 (2024)"
            if escolha["released_at"] > ULTIMA_EDICAO_EM_PORTUGUES
            else ""
        )
        console.print(
            f"  [yellow]![/] {escolha['name']} ({codigo.upper()}) nao tem carta "
            f"em portugues{motivo}."
        )
        if not await questionary.confirm(
            "Listar as cartas em ingles?", default=False
        ).ask_async():
            return
        async with cronometrar(console, f"Buscando cartas de {codigo.upper()} em inglês"):
            cartas = await find_cards_by_set(codigo, lang="en")

    await _escolher_e_gerar(cartas)


FLUXOS_CARTAS = {
    "Buscar por nome": _fluxo_carta_por_nome,
    "Buscar por termo": _fluxo_carta_por_termo,
    "Escolher por edicao": _fluxo_carta_por_edicao,
}


# --- Fluxos de Decks -------------------------------------------------------


async def _fluxo_deck_de_arquivo() -> None:
    caminho_texto = await questionary.path("Arquivo da lista (.txt ou .dec):").ask_async()
    if not caminho_texto:
        return
    entradas = cartas_unicas(ler_arquivo(Path(caminho_texto.strip().strip('"'))))
    console.print(f"  {len(entradas)} cartas distintas na lista.")

    async with cronometrar(console, "Resolvendo cartas no Scryfall"):
        cartas, avisos = await buscar_cartas_do_deck(entradas)
    for aviso in avisos:
        console.print(f"  [yellow]![/] {aviso}")
    if not cartas:
        return

    nome_do_deck = slug(Path(caminho_texto.strip().strip('"')).stem)
    geradas = await _escolher_e_gerar(
        cartas, pre_marcadas=True, pasta_destino=DECKS_DIR / nome_do_deck
    )
    if not geradas:
        return

    # Aqui ainda temos quantas copias o deck pede de cada carta; o fluxo de PDF
    # sozinho so enxerga os arquivos da pasta, 1 de cada.
    total = sum(copias for _, copias in geradas)
    if await questionary.confirm(
        f"Montar o PDF agora, com as {total} copias que o deck pede?", default=True
    ).ask_async():
        async with cronometrar(console, "Montando o PDF"):
            folhas = montar_lote(repetir_por_copias(geradas))
            destino = print_pdf.exportar_pdf(folhas, f"{nome_do_deck}.pdf")
        console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


FLUXOS_DECKS = {"Importar lista de arquivo": _fluxo_deck_de_arquivo}


# --- Fluxos de PDF ---------------------------------------------------------


def _pastas_com_cartas() -> list[Path]:
    raiz = Path(OUTPUT_DIR)
    return [p for p in sorted(raiz.rglob("*")) if p.is_dir() and any(p.glob("*.png"))]


async def _escolher_cartas_para_imprimir() -> list[Path]:
    pastas = _pastas_com_cartas()
    if not pastas:
        console.print(f"  [red]![/] Nenhuma carta gerada em {OUTPUT_DIR}.")
        return []
    escolhidas = await questionary.checkbox(
        "Selecione as pastas a imprimir:",
        choices=[
            questionary.Choice(f"{p} ({len(list(p.glob('*.png')))} cartas)", p)
            for p in pastas
        ],
    ).ask_async()
    if not escolhidas:
        return []
    return [caminho for pasta in escolhidas for caminho in sorted(pasta.glob("*.png"))]


INSTRUCOES_PREVIEW = """\
[bold]Antes de imprimir de verdade:[/]
 1. Ao mandar o PDF pra impressora, confira: papel A4, [bold]"Tamanho Real" /
    sem escala (100%)[/] - NUNCA "Ajustar a pagina", senao a grade sai de
    posicao.
 2. Pra esse teste, imprima em [bold]1 folha de sulfite comum[/] - so depois
    de bater o alinhamento e que vale gastar o papel bom.
 3. Depois de imprimir, meca 1 carta com regua: tem que dar 63,5x88,9mm
    certinho, cortando bem no meio da linha vermelha entre as celulas.
"""


async def _fluxo_montar_pdf() -> None:
    cartas = await _escolher_cartas_para_imprimir()
    if not cartas:
        return
    async with cronometrar(console, "Montando o PDF"):
        destino = print_pdf.exportar_pdf(montar_lote(cartas), "cartas.pdf")
    console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


async def _fluxo_preview() -> None:
    console.print(
        Panel(INSTRUCOES_PREVIEW, title="Prova de impressao", border_style="yellow")
    )
    cartas = await _escolher_cartas_para_imprimir()
    if not cartas:
        return
    cartas_teste = cartas[: layout.CARTAS_POR_FOLHA]
    if len(cartas_teste) < len(cartas):
        console.print(
            f"  [yellow]![/] Prova usa so as primeiras {len(cartas_teste)} carta(s) "
            "(1 folha) - o resto fica de fora desse teste"
        )
    async with cronometrar(console, "Montando a prova"):
        destino = print_pdf.exportar_pdf(montar_lote(cartas_teste), "prova-impressao.pdf")
    console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


FLUXOS_IMPRIMIR = {
    "Montar PDF": _fluxo_montar_pdf,
    "Preview (so 1 folha)": _fluxo_preview,
}


# --- Menu principal --------------------------------------------------------


async def _rodar_submenu(titulo: str, fluxos: dict) -> None:
    while True:
        escolha = await questionary.select(
            titulo, choices=[*fluxos, VOLTAR]
        ).ask_async()
        if escolha is None or escolha == VOLTAR:
            return
        try:
            await fluxos[escolha]()
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelado.[/]")
        except AppError as erro:
            console.print(f"  [red]![/] {erro.message}")
        except Exception as erro:  # noqa: BLE001 - 1 fluxo com erro nao pode derrubar o menu inteiro
            console.print(f"  [red]![/] Erro inesperado: {erro}")
        console.print()


async def rodar_menu() -> None:
    mostrar_banner()
    while True:
        categoria = await questionary.select(
            "O que voce quer fazer?",
            choices=[CATEGORIA_CARTAS, CATEGORIA_DECKS, CATEGORIA_IMPRIMIR, OPCAO_SAIR],
        ).ask_async()
        if categoria is None or categoria == OPCAO_SAIR:
            break
        if categoria == CATEGORIA_CARTAS:
            await _rodar_submenu("Cartas - o que fazer?", FLUXOS_CARTAS)
        elif categoria == CATEGORIA_DECKS:
            await _rodar_submenu("Decks - o que fazer?", FLUXOS_DECKS)
        else:
            await _rodar_submenu("PDF - o que fazer?", FLUXOS_IMPRIMIR)


def main() -> None:
    configurar_stdio_utf8()
    try:
        asyncio.run(rodar_menu())
    except KeyboardInterrupt:
        console.print("\nAte mais!")
