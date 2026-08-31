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

from app.cards.estruturais import (
    DeckEstrutural,
    buscar_entradas_do_deck,
    list_decks_estruturais,
    list_tipos_estruturais,
)
from app.cards import fichas
from app.cards.fichas import FichaDoDeck
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
from app.deck.texto import (
    Chave,
    EntradaDeDeck,
    cartas_unicas,
    chave_da_entrada,
    ler_arquivo,
    travar_impressoes,
)
from app.errors import AppError
from app.maker.service import (
    MOLDURAS,
    MOLDURA_PADRAO,
    PASTA_CARTAS_AVULSAS,
    fill_card,
    moldura_sugerida,
)
from app.print import layout
from app.print import pdf as print_pdf
from app.print import verso
from app.print.service import escrever_copias, ler_copias, montar_lote, repetir_por_copias
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


async def _escolher_impressoes(
    pares: list[tuple[EntradaDeDeck, ScryfallCard]],
) -> dict[Chave, tuple[str, str]]:
    """Troca a impressao das cartas que a lista deixou sem edicao travada.

    Linha sem "(EDICAO) NUMERO" cai na primeira impressao que o Scryfall
    devolver, sem escolha nem preview (ver DECK.md) - o que pesa em terreno
    basico e em carta com muitas variantes. Aqui da pra marcar em quais isso
    importa e escolher olhando a arte; as nao marcadas seguem no automatico.

    Troca a carta no proprio `pares` e devolve as escolhas por chave de linha,
    pra quem tiver o arquivo em maos poder travar a escolha nele.
    """
    soltas = [(entrada, carta) for entrada, carta in pares if not entrada.set]
    if not soltas:
        return {}

    marcadas = await questionary.checkbox(
        "Escolher a impressao de quais cartas?",
        choices=[
            questionary.Choice(
                f"{carta.nome_exibido} - hoje {carta.set.upper()} #{carta.collector_number}",
                chave_da_entrada(entrada),
            )
            for entrada, carta in soltas
        ],
    ).ask_async()
    if not marcadas:
        return {}

    trocas: dict[Chave, tuple[str, str]] = {}
    marcadas = set(marcadas)
    for indice, (entrada, carta) in enumerate(pares):
        chave = chave_da_entrada(entrada)
        if chave not in marcadas:
            continue
        impressoes = await search_cards(carta.name, lang=carta.lang)
        if len(impressoes) <= 1:
            console.print(f'  [dim]"{carta.nome_exibido}" so tem 1 impressao.[/]')
            continue
        escolhida = await escolher_impressao(impressoes)
        escolhida.copias = carta.copias
        pares[indice] = (entrada, escolhida)
        trocas[chave] = (escolhida.set, escolhida.collector_number)
    return trocas


def _nome_da_ficha(ficha: FichaDoDeck) -> str:
    return ficha.carta.arena.nome if ficha.carta.arena else ficha.carta.nome_exibido


async def _escolher_fichas(cartas: list[ScryfallCard]) -> list[ScryfallCard]:
    """Fichas que as cartas do deck criam, pra imprimir junto.

    Quantas copias de cada uma nao da pra deduzir do deck - a carta diz que
    cria ficha, nao quantas voce vai querer na mesa -, entao a quantidade e
    sempre perguntada, com 1 de padrao.
    """
    async with cronometrar(console, "Procurando fichas que o deck cria"):
        achadas = await fichas.descobrir(cartas)
    if not achadas:
        return []

    marcadas = await questionary.checkbox(
        "Gerar quais fichas?",
        choices=[
            questionary.Choice(
                f"{_nome_da_ficha(ficha)} - de {', '.join(ficha.criada_por)}", ficha
            )
            for ficha in achadas
        ],
    ).ask_async()
    if not marcadas:
        return []

    escolhidas = []
    for ficha in marcadas:
        resposta = await questionary.text(
            f"Quantas copias de {_nome_da_ficha(ficha)}?",
            default="1",
            validate=_validar_quantidade,
        ).ask_async()
        ficha.carta.copias = int(resposta) if resposta else 1
        escolhidas.append(ficha.carta)
    return escolhidas


async def _finalizar_fluxo_deck(cartas: list[ScryfallCard], nome_do_deck: str, pasta_destino: Path) -> None:
    """Rabo comum a todo fluxo de deck depois de resolvido no Scryfall: mostra
    checkbox de selecao, gera as escolhidas e oferece montar o PDF com as
    copias que o deck pede."""
    geradas = await _escolher_e_gerar(cartas, pre_marcadas=True, pasta_destino=pasta_destino)
    if not geradas:
        return
    escrever_copias(pasta_destino, geradas)

    total = sum(copias for _, copias in geradas)
    if await questionary.confirm(
        f"Montar o PDF agora, com as {total} copias que o deck pede?", default=True
    ).ask_async():
        async with cronometrar(console, "Montando o PDF"):
            folhas = montar_lote(repetir_por_copias(geradas))
            destino = print_pdf.exportar_pdf(folhas, f"{nome_do_deck}.pdf")
        console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


async def _fluxo_deck_de_arquivo() -> None:
    caminho_texto = await questionary.path("Arquivo da lista (.txt ou .dec):").ask_async()
    if not caminho_texto:
        return
    caminho = Path(caminho_texto.strip().strip('"'))
    entradas = cartas_unicas(ler_arquivo(caminho))
    console.print(f"  {len(entradas)} cartas distintas na lista.")

    async with cronometrar(console, "Resolvendo cartas no Scryfall"):
        pares, avisos = await buscar_cartas_do_deck(entradas)
    for aviso in avisos:
        console.print(f"  [yellow]![/] {aviso}")
    if not pares:
        return

    trocas = await _escolher_impressoes(pares)
    if trocas:
        linhas = travar_impressoes(caminho, trocas)
        console.print(f"  [green]OK[/] {linhas} linha(s) travadas em [bold]{caminho.name}[/].")

    cartas = [carta for _, carta in pares]
    cartas += await _escolher_fichas(cartas)

    nome_do_deck = slug(caminho.stem)
    await _finalizar_fluxo_deck(cartas, nome_do_deck, DECKS_DIR / nome_do_deck)


async def _fluxo_deck_estrutural() -> None:
    """Decks pre-construidos oficiais (Commander, Planeswalker, Challenger...)
    via MTGJSON - ver app.cards.estruturais. Navega por tipo e depois por
    nome, porque o indice tem centenas de decks."""
    async with cronometrar(console, "Carregando indice de decks estruturais"):
        tipos = await list_tipos_estruturais()
    if not tipos:
        console.print("  [red]![/] Nao foi possivel carregar o indice de decks estruturais.")
        return
    tipo = await questionary.select("Qual tipo de deck?", choices=[*tipos, VOLTAR]).ask_async()
    if tipo is None or tipo == VOLTAR:
        return

    decks = await list_decks_estruturais(tipo)
    escolhido: DeckEstrutural | None = await questionary.select(
        "Qual deck?",
        choices=[
            questionary.Choice(f"{d.nome} ({d.released_at[:4]})", d) for d in decks
        ]
        + [VOLTAR],
    ).ask_async()
    if escolhido is None or escolhido == VOLTAR:
        return

    async with cronometrar(console, f'Baixando "{escolhido.nome}"'):
        entradas = cartas_unicas(await buscar_entradas_do_deck(escolhido.arquivo))
    console.print(f"  {len(entradas)} cartas distintas na lista.")

    async with cronometrar(console, "Resolvendo cartas no Scryfall"):
        pares, avisos = await buscar_cartas_do_deck(entradas)
    for aviso in avisos:
        console.print(f"  [yellow]![/] {aviso}")
    if not pares:
        return

    # Deck estrutural vem do MTGJSON, nao de um .txt local: nao ha arquivo
    # pra travar a impressao escolhida nele (ver travar_impressoes).
    await _escolher_impressoes(pares)

    cartas = [carta for _, carta in pares]
    cartas += await _escolher_fichas(cartas)

    nome_do_deck = slug(escolhido.nome)
    await _finalizar_fluxo_deck(
        cartas, nome_do_deck, DECKS_DIR / "decks-estruturais" / nome_do_deck
    )


FLUXOS_DECKS = {
    "Importar lista de arquivo": _fluxo_deck_de_arquivo,
    "Buscar por estrutural": _fluxo_deck_estrutural,
}


# --- Fluxos de PDF ---------------------------------------------------------


def _pastas_de_deck() -> list[Path]:
    """Toda pasta com png que nao seja a de cartas avulsas (PASTA_CARTAS_AVULSAS)
    - 1 por deck, veja o comentario de _opcoes_selecao pro motivo. Pega
    qualquer profundidade porque cada fluxo de deck monta a propria (import de
    arquivo cai direto em DECKS_DIR/<nome>, estrutural em
    DECKS_DIR/decks-estruturais/<nome>)."""
    raiz = Path(OUTPUT_DIR)
    return [
        p
        for p in sorted(raiz.rglob("*"))
        if p.is_dir() and p != PASTA_CARTAS_AVULSAS and any(p.glob("*.png"))
    ]


def _opcoes_selecao() -> list[questionary.Choice]:
    """1 opcao por carta avulsa (cards/*.png) + 1 opcao por deck INTEIRO (cada
    pasta de _pastas_de_deck, todas as cartas dali juntas numa escolha so) -
    mesmo esquema do script-yugioh-maker: escolher o deck marca ele de 1 vez,
    sem precisar marcar carta por carta. O valor de cada Choice ja e a lista
    de (caminho, copias) que aquela opcao representa - avulsa usa copias=None
    (pergunta depois), deck usa o que tiver salvo em copias.txt (1 se nao
    tiver, ver app.print.service)."""
    opcoes = []
    if PASTA_CARTAS_AVULSAS.exists():
        opcoes += [
            questionary.Choice(f"cards/{caminho.name}", [(caminho, None)])
            for caminho in sorted(PASTA_CARTAS_AVULSAS.glob("*.png"))
        ]
    for pasta_deck in _pastas_de_deck():
        imagens = sorted(pasta_deck.glob("*.png"))
        copias = ler_copias(pasta_deck)
        rotulo = pasta_deck.relative_to(OUTPUT_DIR).as_posix()
        opcoes.append(
            questionary.Choice(
                f"[deck] {rotulo} ({len(imagens)} cartas)",
                [(imagem, copias.get(imagem.name, 1)) for imagem in imagens],
            )
        )
    return opcoes


def _validar_quantidade(texto: str) -> bool | str:
    if not texto or (texto.isdigit() and int(texto) > 0):
        return True
    return "Numero inteiro maior que 0 (ou vazio pra 1)"


async def _escolher_cartas_para_imprimir() -> list[tuple[Path, int]]:
    opcoes = _opcoes_selecao()
    if not opcoes:
        console.print(f"  [red]![/] Nenhuma carta gerada em {OUTPUT_DIR}.")
        return []
    escolhidos = await questionary.checkbox(
        "Selecione cartas avulsas e/ou decks inteiros:", choices=opcoes
    ).ask_async()
    if not escolhidos:
        return []
    pares = [par for grupo in escolhidos for par in grupo]

    resultado: list[tuple[Path, int]] = []
    for caminho, copias in pares:
        if copias is None:
            resposta = await questionary.text(
                f"Quantas copias de {caminho.stem}?",
                default="1",
                validate=_validar_quantidade,
            ).ask_async()
            copias = int(resposta) if resposta else 1
        resultado.append((caminho, copias))
    return resultado


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
    pares = await _escolher_cartas_para_imprimir()
    if not pares:
        return
    async with cronometrar(console, "Montando o PDF"):
        destino = print_pdf.exportar_pdf(montar_lote(repetir_por_copias(pares)), "cartas.pdf")
    console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


async def _fluxo_preview() -> None:
    console.print(
        Panel(INSTRUCOES_PREVIEW, title="Prova de impressao", border_style="yellow")
    )
    pares = await _escolher_cartas_para_imprimir()
    if not pares:
        return
    cartas = repetir_por_copias(pares)
    cartas_teste = cartas[: layout.CARTAS_POR_FOLHA]
    if len(cartas_teste) < len(cartas):
        console.print(
            f"  [yellow]![/] Prova usa so as primeiras {len(cartas_teste)} carta(s) "
            "(1 folha) - o resto fica de fora desse teste"
        )
    async with cronometrar(console, "Montando a prova"):
        destino = print_pdf.exportar_pdf(montar_lote(cartas_teste), "prova-impressao.pdf")
    console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


async def _fluxo_gerar_verso() -> None:
    async with cronometrar(console, "Montando o verso generico"):
        destino = print_pdf.exportar_pdf([verso.montar_folha()], "verso.pdf")
    console.print(
        f"  [green]OK[/] salvo em [bold]{destino}[/] - so 1 folha, porque toda "
        "celula sai igual: imprima ela no verso de qualquer folha de frente, "
        "quantas vezes precisar."
    )


FLUXOS_IMPRIMIR = {
    "Montar PDF": _fluxo_montar_pdf,
    "Gerar verso generico": _fluxo_gerar_verso,
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
