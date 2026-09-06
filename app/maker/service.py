"""Automacao do Card Conjurer (Playwright async).

O gerador roda auto-hospedado em vendor/ (ver app.vendor), servido em
localhost, entao nao ha preenchimento campo a campo: da pra chamar as funcoes
globais dele, que ja sabem importar do Scryfall no idioma escolhido, escolher a
moldura e compor as camadas. A imagem sai lida direto do `cardCanvas`.
"""

import asyncio
import base64
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from playwright.async_api import Browser, Page, Route, async_playwright

from app.cards.enums import Layout
from app.cards.models import ScryfallCard
from app.cards.palavras_chave import palavras_de_habilidade
from app.cards.service import e_terreno_basico
from app.config import (
    CARDCONJURER_URL,
    HEADLESS,
    OUTPUT_DIR,
)
from app.errors import BadRequestError, UpstreamError
from app.maker import arte
from app.maker.browser import carregar
from app.slug import slug
from app.vendor.server import ServidorCardConjurer

# Carta avulsa; deck passa a propria pasta em `pasta_destino`.
PASTA_CARTAS_AVULSAS = Path(OUTPUT_DIR) / "cards"

# Molduras do #autoFrame do gerador. A chave e o que aparece no menu.
MOLDURAS = {
    "Regular": "M15Regular-1",
    "Regular (fiel)": "M15RegularNew",
    "Arte estendida": "M15BoxTopper",
    "Arte estendida (caixa menor)": "M15ExtendedArtShort",
    "Universes Beyond": "UB",
    "Etched": "Etched",
    "Borderless": "Borderless",
    "Phyrexiana": "Praetors",
    "8th Edition": "8th",
    "Seventh Edition": "Seventh",
    "Full art (fiel)": "FullArtNew",
    "Circuit": "Circuit",
    "Terreno basico de arte cheia": "TextlessBasics2022",
    "Terreno basico sem borda": "TextlessBasicsBorderless",
}
MOLDURA_PADRAO = "M15Regular-1"


def moldura_sugerida(carta: ScryfallCard) -> str:
    """Moldura do #autoFrame mais proxima da impressao real.

    O #autoFrame decide sozinho so cor e tipo; a familia de moldura (M15, 8a
    edicao, borderless...) sai da propria impressao no Scryfall
    (frame/border_color/frame_effects/full_art). Quem quiser outra troca depois.
    """
    efeitos = carta.frame_effects or []
    # Antes das outras: a carta de papel nao tem janela de arte nem caixa de
    # regras, so a borda da cor e o simbolo de mana no canto, e nenhuma moldura
    # de carta comum chega nisso.
    if e_terreno_basico(carta) and carta.full_art:
        # Sem borda vai mais longe: arte na carta inteira, nome na faixa de baixo.
        if carta.border_color == "borderless":
            return MOLDURAS["Terreno basico sem borda"]
        return MOLDURAS["Terreno basico de arte cheia"]
    if "etched" in efeitos:
        return MOLDURAS["Etched"]
    # Antes do full art: arte cheia E sem borda fica melhor na borderless, que
    # leva a arte ate a aresta.
    if carta.border_color == "borderless":
        return MOLDURAS["Borderless"]
    if carta.full_art:
        return MOLDURAS["Full art (fiel)"]
    if "extendedart" in efeitos:
        return MOLDURAS["Arte estendida"]
    # Depois das de acabamento: impressao de Universes Beyond que tambem e
    # borderless ou de arte estendida usa a moldura do acabamento.
    if "universesbeyond" in (carta.promo_types or []):
        return MOLDURAS["Universes Beyond"]
    if carta.frame == "2003":
        return MOLDURAS["8th Edition"]
    if carta.frame == "1997":
        return MOLDURAS["Seventh Edition"]
    # frame "1993" e "future" nao tem equivalente no catalogo.
    return MOLDURA_PADRAO


# Rodando local, moldura e simbolo vem do disco; so estes hosts precisam sair
# pra internet.
HOSTS_LIBERADOS = (
    "127.0.0.1",
    "localhost",
    "api.scryfall.com",
    "cards.scryfall.io",
    "svgs.scryfall.io",
    "www.mtgpics.com",
    "mtgpics.com",
)

# So pra existir um card.text na abertura: sem ele, changeCardIndex() e
# autoFrame() quebram. A moldura definitiva vem do autoFrame.
GRUPO_INICIAL = "Standard-3"
PACOTE_INICIAL = "M15Regular-1"

# A Wizards trocou o rodape em March of the Machine: antes vinha o numero com
# tres digitos e o total da colecao ("017/281 C"), depois so o numero com quatro
# ("R 0011"). O gerador monta os dois formatos sozinho - o que falta e dizer
# qual, pela data da impressao.
PRIMEIRA_EDICAO_COM_NUMERO_DE_QUATRO_DIGITOS = date(2023, 4, 21)

# Cada um destes rende duas imagens, uma por face, e o fluxo daqui salva uma so.
LAYOUTS_DE_DUAS_FACES = frozenset(
    {
        Layout.TRANSFORM,
        Layout.MODAL_DFC,
        Layout.MELD,
        Layout.REVERSIBLE_CARD,
        Layout.DOUBLE_FACED_TOKEN,
        Layout.ART_SERIES,
    }
)

# Layout que precisa de moldura propria - capitulo na lateral, duas metades,
# caixa de lealdade. Como o fluxo daqui monta so a moldura normal, a carta sai
# com o texto espremido na caixa de regras: melhor recusar.
LAYOUTS_SEM_MOLDURA_PROPRIA = frozenset(
    {
        Layout.SAGA,
        Layout.SPLIT,
        Layout.ADVENTURE,
        Layout.FLIP,
        Layout.LEVELER,
        Layout.CLASS,
        Layout.CASE,
        Layout.MUTATE,
        Layout.BATTLE,
        Layout.PLANAR,
        Layout.SCHEME,
        Layout.VANGUARD,
    }
)

_IMPRESSAO_DIGITAL = carregar("impressao-digital")

_SELECIONAR_IMPRESSAO = carregar("selecionar-impressao")

_IMPORTAR_CARTAS = carregar("importar-cartas")

_APLICAR_MOLDURA = carregar("aplicar-moldura")

_AJUSTAR_TITULO = carregar("ajustar-titulo")

_AJUSTAR_LINHA_DE_TIPO = carregar("ajustar-linha-de-tipo")


_AJUSTAR_CAIXA_DE_REGRAS = carregar("ajustar-caixa-de-regras")


# O simbolo de mana grande na caixa do terreno basico e desenhado como marca
# d'agua, e ela precisa de imagem e cor: com watermarkLeft em 'none' nada e
# pintado, com 'default' sai o svg cru, preto. Os hex sao os do proprio seletor
# do gerador.
MARCA_DAGUA_DE_TERRENO = {
    "W": ("/img/watermarks/w.svg", "#b79d58"),
    "U": ("/img/watermarks/u.svg", "#8cacc5"),
    "B": ("/img/watermarks/b.svg", "#5e5e5e"),
    "R": ("/img/watermarks/r.svg", "#c66d39"),
    "G": ("/img/watermarks/g.svg", "#598c52"),
}

_APLICAR_MARCA_DAGUA = carregar("aplicar-marca-dagua")

INTERVALO_AMOSTRA = 0.3
AMOSTRAS_IGUAIS = 3  # leituras seguidas sem mudanca = desenho terminou
TEMPO_LIMITE_DESENHO = 45.0
TEMPO_LIMITE_ELEMENTO = 30_000  # milissegundos, como o Playwright espera


def _marca_dagua(carta: ScryfallCard, moldura: str) -> tuple[str, str] | None:
    """Imagem e cor da marca d'agua desta carta, ou None pra deixar sem.

    So terreno basico usa, e a cor sai do simbolo de mana do oracle_text
    ("({T}: Add {R}.)"). Wastes fica de fora (o gerador nao tem svg de incolor)
    e as molduras de arte cheia tambem, que ja trazem o simbolo como camada.
    """
    if moldura in (
        MOLDURAS["Terreno basico de arte cheia"],
        MOLDURAS["Terreno basico sem borda"],
    ):
        return None
    if not e_terreno_basico(carta):
        return None
    simbolo = re.search(r"\{([WUBRG])\}", carta.oracle_text or "")
    return MARCA_DAGUA_DE_TERRENO.get(simbolo.group(1)) if simbolo else None


def _texto_de_reserva(carta: ScryfallCard) -> str:
    """Texto de regras pro caso do Scryfall nao trazer o traduzido.

    Terreno basico fica de fora: printed_text nulo ali nao e dado faltando, e a
    carta nao ter texto mesmo - so a marca d'agua do simbolo de mana.
    """
    if e_terreno_basico(carta):
        return ""
    return carta.texto_exibido or ""


def _rodape_de_quatro_digitos(carta: ScryfallCard) -> bool:
    """Se esta impressao usa o rodape novo, so com o numero em quatro digitos."""
    return (
        carta.released_at is not None
        and carta.released_at >= PRIMEIRA_EDICAO_COM_NUMERO_DE_QUATRO_DIGITOS
    )


def _e_planeswalker(carta: ScryfallCard) -> bool:
    """Planeswalker tem layout "normal" no Scryfall: o que o separa e a linha de
    tipo, e a moldura dele precisa da caixa de lealdade."""
    return "planeswalker" in (carta.type_line or "").lower()


def _texto_traduzido(carta: ScryfallCard) -> str | None:
    """Texto de regras a impor na impressao em ingles, ou None pra deixar o que
    o Scryfall trouxer.

    So terreno basico impoe: o lembrete em ingles do oracle_text nao existe na
    carta de papel.
    """
    if carta.lang == "en" and e_terreno_basico(carta):
        return ""
    return None


async def _filtrar_rede(rota: Route) -> None:
    """Deixa passar so o servidor local e as fontes de dados e arte."""
    host = rota.request.url.split("/")[2].split(":")[0]
    if host in HOSTS_LIBERADOS:
        await rota.continue_()
    else:
        await rota.abort()


@asynccontextmanager
async def navegador():
    """Abre 1 Chromium com o servidor do Card Conjurer no ar.

    Pra carta avulsa; quem gera lote abre uma vez e reusa, que e o gargalo de
    velocidade.
    """
    servidor = ServidorCardConjurer().start()
    async with async_playwright() as p:
        navegador_aberto = await p.chromium.launch(headless=HEADLESS)
        try:
            yield navegador_aberto
        finally:
            await navegador_aberto.close()
            servidor.stop()


async def abrir_pagina(browser: Browser) -> Page:
    """Pagina do criador pronta pra receber import.

    enableImportCollectorInfo preenche numero, raridade, edicao e idioma no
    rodape e autoLoadFrameVersion aplica o pacote de molduras sozinho.
    enableCollectorInfo precisa vir escrito daqui: sem a chave, o Card Conjurer
    grava 'true' mas nao marca a caixa, e o rodape so apareceria na visita
    seguinte.
    """
    contexto = await browser.new_context(viewport={"width": 1400, "height": 1000})
    await contexto.route("**/*", _filtrar_rede)
    page = await contexto.new_page()
    await page.add_init_script(
        "localStorage.setItem('enableImportCollectorInfo', 'true');"
        "localStorage.setItem('autoLoadFrameVersion', 'true');"
        "localStorage.setItem('enableCollectorInfo', 'true');"
    )
    # O parametro mtgpics liga a arte grande; sem ele fica no art_crop 626x457.
    await page.goto(f"{CARDCONJURER_URL}/creator/?mtgpics=1", wait_until="load")
    await page.wait_for_function("typeof fetchScryfallData === 'function'")
    await _carregar_moldura_inicial(page)
    await _registrar_fonte_sem_bug(page)
    return page


# A mesma Beleren sob outro nome (ver browser/trocar-fonte-sem-bug.js).
FONTE_SEM_BUG = "belerenb-sembug"

_TROCAR_PARA_FONTE_SEM_BUG = carregar("trocar-fonte-sem-bug")


async def _registrar_fonte_sem_bug(page: Page) -> None:
    await page.evaluate(
        """(nomeFonte) => {
            const fonte = new FontFace(nomeFonte, "url(/fonts/beleren-b.ttf)");
            return fonte.load().then((carregada) => { document.fonts.add(carregada); });
        }""",
        FONTE_SEM_BUG,
    )


async def _carregar_moldura_inicial(page: Page) -> None:
    """Carrega um pacote de molduras pra existir um card.text.

    A pagina abre com `card` sem `text`, e nesse estado o import e a moldura
    automatica quebram. Escolher grupo e pacote e o que a aba Frame faz.
    """
    await page.select_option("#selectFrameGroup", GRUPO_INICIAL)
    await page.wait_for_function(
        "document.querySelector('#selectFramePack').options.length > 0",
        timeout=TEMPO_LIMITE_ELEMENTO,
    )
    await page.select_option("#selectFramePack", PACOTE_INICIAL)
    await page.wait_for_function(
        "typeof card !== 'undefined' && card.text && card.text.title",
        timeout=TEMPO_LIMITE_ELEMENTO,
    )


async def _esperar_desenho(page: Page) -> None:
    """Espera o canvas parar de mudar.

    O gerador nao avisa quando terminou: arte, simbolo de expansao e camadas de
    moldura chegam cada um no seu tempo.
    """
    limite = asyncio.get_running_loop().time() + TEMPO_LIMITE_DESENHO
    anterior = None
    iguais = 0
    while asyncio.get_running_loop().time() < limite:
        atual = await page.evaluate(_IMPRESSAO_DIGITAL)
        if atual is not None and atual == anterior:
            iguais += 1
            if iguais >= AMOSTRAS_IGUAIS:
                return
        else:
            iguais = 0
        anterior = atual
        await asyncio.sleep(INTERVALO_AMOSTRA)
    raise UpstreamError(f"O desenho nao estabilizou em {TEMPO_LIMITE_DESENHO:.0f}s")


async def _selecionar_impressao(page: Page, carta: ScryfallCard) -> bool:
    """Escolhe no gerador a mesma impressao que a consulta trouxe.

    Devolve se precisou mesmo trocar: trocar a toa dispara uma segunda consulta
    da edicao e o numero do colecionador sai duplicado ("187/361/361").
    """
    indice = await page.evaluate(
        "(id) => scryfallCard.findIndex(c => c.id === id)", carta.id
    )
    if indice is None or indice < 0:
        # A impressao exata nao veio na busca do gerador. Fica a que o
        # importCard() aplicou sozinho: um indice arbitrario pode nao ser opcao
        # valida do <select> e travar o changeCardIndex().
        return False
    atual = await page.evaluate(
        "() => Number(document.querySelector('#import-index').value)"
    )
    if indice == atual:
        return False
    await page.evaluate(_SELECIONAR_IMPRESSAO, indice)
    return True


async def _aplicar_arte(page: Page, carta: ScryfallCard) -> bool:
    """Troca a arte que o gerador achou sozinho pela maior disponivel.

    Quem escolhe e confere e o app.maker.arte; aqui a imagem so e entregue.
    """
    data_url = await arte.buscar(carta)
    if data_url is None:
        return False
    await page.evaluate("(src) => uploadArt(src, 'autoFit')", data_url)
    await _esperar_desenho(page)
    return True


async def _aplicar_marca_dagua(page: Page, carta: ScryfallCard, moldura: str) -> None:
    """Precisa rodar depois da moldura: os limites onde a marca d'agua e
    encaixada (card.watermarkBounds) vem do pacote de molduras."""
    marca = _marca_dagua(carta, moldura)
    if marca is None:
        return
    imagem, cor = marca
    await page.evaluate(_APLICAR_MARCA_DAGUA, {"imagem": imagem, "cor": cor})
    await _esperar_desenho(page)


async def _redesenhar_texto_final(page: Page) -> None:
    """Ultimo passo antes de salvar: troca a fonte com bug pelo alias sem bug
    (ver FONTE_SEM_BUG) e redesenha o texto de fora da cadeia de callbacks do
    XHR do fetchScryfallData.

    Redesenhar por fora importa: quando a carta fica no indice 0, o
    changeCardIndex() roda encadeado no onreadystatechange do XHR e o titulo
    sai com o ultimo glifo faltando em moldura tipo "seventh". So
    drawTextBuffer(), nunca changeCardIndex() de novo - esse reconsultaria
    /sets e duplicaria o numero do colecionador (ver _selecionar_impressao).
    """
    await page.evaluate(_TROCAR_PARA_FONTE_SEM_BUG, FONTE_SEM_BUG)
    await page.evaluate(_AJUSTAR_TITULO)
    await page.evaluate(_AJUSTAR_LINHA_DE_TIPO)
    await page.evaluate(_AJUSTAR_CAIXA_DE_REGRAS)
    await page.evaluate("() => drawTextBuffer()")
    await _esperar_desenho(page)


_APLICAR_SELO = carregar("aplicar-selo")


async def _aplicar_selo(page: Page, carta: ScryfallCard) -> None:
    """Precisa rodar depois da moldura: a cor do selo e a dela, e sai do
    card.frames que o autoFrame monta."""
    if not carta.security_stamp:
        return
    await page.evaluate(_APLICAR_SELO, {"formato": carta.security_stamp})
    await _esperar_desenho(page)


_APLICAR_NOME_TRADUZIDO = carregar("aplicar-nome-traduzido")


async def _aplicar_nome_traduzido(
    page: Page, carta: ScryfallCard, *, preferir_arena: bool
) -> None:
    """Poe no titulo o nome traduzido montado fora do Scryfall: o do terreno
    basico sem impressao em portugues e o do MTG Arena."""
    if carta.lang != "en":
        return
    do_arena = carta.arena.nome if preferir_arena and carta.arena else None
    nome = do_arena or carta.printed_name
    if not nome:
        return
    await page.evaluate(_APLICAR_NOME_TRADUZIDO, nome)


async def _aplicar_moldura(page: Page, carta: ScryfallCard) -> None:
    """Refaz a moldura automatica com a linha de tipo em ingles (ver
    _APLICAR_MOLDURA). Depois do import: e ele que enche card.text.type."""
    await page.evaluate(
        _APLICAR_MOLDURA,
        {
            "tipoIngles": carta.type_line or "",
            "regrasIngles": carta.oracle_text or "",
        },
    )
    await _esperar_desenho(page)


async def _esperar_fontes(page: Page) -> None:
    """Espera a fonte customizada carregar antes de ler o canvas - senao a
    captura pega o desenho no meio de uma troca de fonte tardia."""
    await page.evaluate("() => document.fonts.ready")


async def _salvar(page: Page, carta: ScryfallCard, pasta_destino: Path | None, moldura: str) -> Path:
    await _esperar_fontes(page)
    data_url = await page.evaluate("() => cardCanvas.toDataURL('image/png')")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        raise UpstreamError("O canvas nao devolveu uma imagem PNG")

    pasta = pasta_destino or PASTA_CARTAS_AVULSAS
    pasta.mkdir(parents=True, exist_ok=True)
    nome_base = f"{carta.nome_exibido}-{carta.set}-{carta.collector_number}"
    # Sem o sufixo, gerar a mesma impressao noutra moldura sobrescreveria.
    if moldura != moldura_sugerida(carta):
        nome_base += f"-{moldura}"
    destino = pasta / f"{slug(nome_base)}.png"
    destino.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
    return destino


async def fill_card(
    carta: ScryfallCard,
    *,
    browser: Browser | None = None,
    pasta_destino: Path | None = None,
    moldura: str | None = None,
    arte_mtgpics: bool = True,
    preferir_arena: bool = False,
) -> Path:
    """Monta a carta no gerador e salva o PNG. Retorna o caminho salvo.

    `browser` reusa um Chromium ja aberto; `pasta_destino` (default
    PASTA_CARTAS_AVULSAS) e onde o arquivo vai parar; `moldura` None deixa
    moldura_sugerida() decidir; `preferir_arena` usa a traducao do MTG Arena
    (ver app.cards.arena) quando ela existir.
    """
    moldura = moldura or moldura_sugerida(carta)
    if carta.layout in LAYOUTS_DE_DUAS_FACES:
        raise BadRequestError(
            f"{carta.nome_exibido} e uma carta de {carta.layout}, que rende duas "
            "imagens; o gerador aqui ainda produz uma face so"
        )
    if carta.layout in LAYOUTS_SEM_MOLDURA_PROPRIA:
        raise BadRequestError(
            f"{carta.nome_exibido} tem layout {carta.layout}, que pede moldura "
            "propria; o gerador aqui monta so a moldura normal e a carta sairia errada"
        )
    if _e_planeswalker(carta):
        raise BadRequestError(
            f"{carta.nome_exibido} e planeswalker, que pede a moldura com caixa de "
            "lealdade; o gerador aqui monta so a moldura normal e a carta sairia errada"
        )

    if browser is not None:
        return await _preencher(browser, carta, pasta_destino, moldura, arte_mtgpics, preferir_arena)
    async with navegador() as proprio:
        return await _preencher(
            proprio, carta, pasta_destino, moldura, arte_mtgpics, preferir_arena
        )


async def _preencher(
    browser: Browser,
    carta: ScryfallCard,
    pasta_destino: Path | None,
    moldura: str,
    arte_mtgpics: bool,
    preferir_arena: bool,
) -> Path:
    page = await abrir_pagina(browser)
    try:
        # Escrito por evaluate, nao por select_option: o onchange do
        # #import-language e o mesmo importChanged() do #importAllPrints (ver
        # abaixo). O #autoFrame fica com select_option porque o onchange dele
        # carrega o pacote de moldura, que e trabalho necessario.
        await page.evaluate(
            "(lang) => { document.querySelector('#import-language').value = lang; }", carta.lang
        )
        await page.select_option("#autoFrame", moldura)
        # setBottomInfoStyle() de novo porque o layout do rodape ja foi montado
        # na abertura da pagina, quando ainda nao se sabia qual carta viria.
        await page.evaluate(
            """(novo) => {
                document.querySelector('#enableNewCollectorStyle').checked = novo;
                return setBottomInfoStyle();
            }""",
            _rodape_de_quatro_digitos(carta),
        )
        # Com todas as impressoes na lista, o gerador casa a arte pela
        # ilustracao da impressao escolhida. Marcado por evaluate, nao por
        # page.check(): o onchange dispara uma busca extra no Scryfall com o
        # #import-name vazio, e so o ESTADO marcado importa (quem le e o
        # artFromScryfall(), nao o evento).
        await page.evaluate("() => { document.querySelector('#importAllPrints').checked = true; }")

        nome_busca = carta.name.split(" // ")[0]
        # A busca abaixo passa unique='prints', o que o importChanged() faria se
        # a chamada viesse pela interface: sem isso vem uma impressao so por
        # nome, e o id da carta escolhida pode nem estar na lista.
        usar_arena = preferir_arena and carta.arena is not None and bool(
            carta.arena.nome or carta.arena.texto
        )
        await page.evaluate(
            _IMPORTAR_CARTAS,
            {
                "nome": nome_busca,
                "idAlvo": carta.id,
                "tipoDeReserva": carta.tipo_exibido or "Card",
                "textoDeReserva": _texto_de_reserva(carta),
                # Impressao em ingles com printed_type_line so acontece quando a
                # traducao foi montada por fora - hoje, as fichas.
                "tipoTraduzido": (
                    carta.printed_type_line if carta.lang == "en" else None
                ),
                "textoTraduzido": _texto_traduzido(carta),
                "palavrasDeHabilidade": list(palavras_de_habilidade()),
                "arenaId": carta.id if usar_arena else None,
                "arenaTexto": carta.arena.texto if usar_arena else None,
                "arenaFlavor": carta.arena.flavor_text if usar_arena else None,
            },
        )
        try:
            await page.wait_for_function(
                "document.querySelector('#import-index').options.length > 0",
                timeout=TEMPO_LIMITE_ELEMENTO,
            )
        except Exception as erro:
            raise UpstreamError(
                f'O Card Conjurer nao trouxe nenhuma impressao para "{carta.name}"'
            ) from erro

        # O importCard() ja aplica a primeira impressao sozinho: deixar essa
        # rodada terminar evita corrida na consulta da edicao.
        await _esperar_desenho(page)
        if await _selecionar_impressao(page, carta):
            await _esperar_desenho(page)
        await _aplicar_moldura(page, carta)
        await _aplicar_selo(page, carta)
        await _aplicar_marca_dagua(page, carta, moldura)
        await _aplicar_nome_traduzido(page, carta, preferir_arena=usar_arena)
        await _redesenhar_texto_final(page)
        if arte_mtgpics:
            await _aplicar_arte(page, carta)
        return await _salvar(page, carta, pasta_destino, moldura)
    finally:
        await page.context.close()
