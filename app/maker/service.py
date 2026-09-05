"""Automacao do Card Conjurer (Playwright async).

Diferente do script-yugioh-maker, o gerador nao e site de terceiro: e o fork
auto-hospedado em vendor/ (ver app.vendor), servido em localhost. Por isso nao
ha preenchimento campo a campo - da pra chamar as funcoes globais do proprio
gerador, que ja sabem importar do Scryfall no idioma escolhido, escolher a
moldura e compor as camadas.

A imagem sai lida direto do `cardCanvas`: o `downloadCard()` do site faz o
mesmo `toDataURL`, mas passando por um `<a download>` que nao interessa aqui.
"""

import asyncio
import base64
import re
from contextlib import asynccontextmanager
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

# pasta padrao pra carta avulsa - quem monta deck passa a propria pasta em
# `pasta_destino`, ver app.cli.menu
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
}
MOLDURA_PADRAO = "M15Regular-1"


def moldura_sugerida(carta: ScryfallCard) -> str:
    """Moldura do #autoFrame mais proxima da impressao real.

    O #autoFrame decide sozinho so cor e tipo (criatura, lendaria etc) - qual
    familia de moldura usar (M15, 8a edicao, borderless...) ele nao sabe. O
    Scryfall guarda isso na propria impressao (frame/border_color/
    frame_effects/full_art), entao da pra resolver sem perguntar - quem quiser
    outra ainda pode trocar depois.
    """
    efeitos = carta.frame_effects or []
    if "etched" in efeitos:
        return MOLDURAS["Etched"]
    # Borderless antes de full art: carta de arte cheia E sem borda (o terreno
    # basico das colecoes recentes) fica melhor na borderless, que leva a arte
    # ate a aresta; a "Full art (fiel)" ainda desenha moldura de pedra em volta.
    if carta.border_color == "borderless":
        return MOLDURAS["Borderless"]
    if carta.full_art:
        return MOLDURAS["Full art (fiel)"]
    if "extendedart" in efeitos:
        return MOLDURAS["Arte estendida"]
    # O showcase "inverted" (o ichor de Phyrexia: Tudo Sera Um) tem a arte
    # sangrando ate a borda; o catalogo do Card Conjurer nao tem essa moldura,
    # e a borderless e a unica que tambem larga a janela de arte.
    if "inverted" in efeitos:
        return MOLDURAS["Borderless"]
    if carta.frame == "2003":
        return MOLDURAS["8th Edition"]
    if carta.frame == "1997":
        return MOLDURAS["Seventh Edition"]
    # frame "1993" (moldura preta/branca antiga) e "future" nao tem
    # equivalente no catalogo do Card Conjurer - cai na M15 por padrao.
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

# Moldura carregada na abertura so pra existir um card.text: sem ele, tanto
# changeCardIndex() quanto autoFrame() quebram. A definitiva vem depois, do
# autoFrame, que troca o pacote sozinho conforme a cor e o tipo da carta.
GRUPO_INICIAL = "Standard-3"
PACOTE_INICIAL = "M15Regular-1"

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

# Layout que precisa de uma moldura propria - capitulo na lateral, duas
# metades, caixa de lealdade. O fluxo daqui monta so a moldura normal, entao
# essas cartas saiam com o texto todo espremido na caixa de regras, sem aviso.
# Recusar e melhor que entregar carta errada calado.
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


# Terreno basico nao tem texto de regras impresso: a caixa leva o simbolo de
# mana grande. Quem desenha isso no gerador e a marca d'agua, e ela precisa da
# imagem e de uma cor - com watermarkLeft em 'none' o watermarkEdited() nao
# pinta nada, e com 'default' sai o svg cru, que e preto. Os cinco hex sao os
# que o proprio seletor de marca d'agua do gerador usa pra cada cor.
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


def _marca_dagua(carta: ScryfallCard) -> tuple[str, str] | None:
    """Imagem e cor da marca d'agua desta carta, ou None pra deixar sem.

    So terreno basico usa por enquanto, e a cor sai do proprio simbolo de mana
    do oracle_text ("({T}: Add {R}.)") - assim nao ha tabela de subtipo pra
    manter. Wastes fica de fora: o gerador nao tem svg de incolor.
    """
    if not e_terreno_basico(carta):
        return None
    simbolo = re.search(r"\{([WUBRG])\}", carta.oracle_text or "")
    return MARCA_DAGUA_DE_TERRENO.get(simbolo.group(1)) if simbolo else None


def _texto_de_reserva(carta: ScryfallCard) -> str:
    """Texto de regras pro caso do Scryfall nao trazer o traduzido.

    Terreno basico fica de fora: printed_text nulo ali nao e dado faltando, e
    a carta realmente nao ter texto (a caixa leva so o simbolo de mana). Sem
    essa excecao o lembrete em ingles do oracle_text - "({T}: Add {W}.)" -
    acabava impresso na carta.
    """
    if e_terreno_basico(carta):
        return ""
    return carta.texto_exibido or ""


def _e_planeswalker(carta: ScryfallCard) -> bool:
    """Planeswalker tem layout "normal" no Scryfall - o que o separa e a linha
    de tipo, e a moldura dele precisa da caixa de lealdade."""
    return "planeswalker" in (carta.type_line or "").lower()


def _texto_traduzido(carta: ScryfallCard) -> str | None:
    """Texto de regras a impor na impressao em ingles, ou None pra deixar o
    que o Scryfall trouxer.

    So terreno basico impoe: ele nao tem regra nenhuma, e o lembrete que vem
    no oracle_text em ingles - "({T}: Add {G}.)" - nao existe na carta de
    papel, que leva so a marca d'agua do simbolo de mana.
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

    Usado por quem gera 1 carta so; quem gera lote abre uma vez e reusa, que e
    o gargalo de velocidade gerando varias (ver app.cli.menu).
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
    rodape; autoLoadFrameVersion faz o pacote de molduras se aplicar sozinho;
    enableCollectorInfo precisa vir escrito daqui porque, quando a chave nao
    existe, o Card Conjurer grava 'true' mas nao marca a caixa - o rodape so
    apareceria na segunda visita a pagina.
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


# Apelido pra mesma Beleren, registrado sob outro nome (ver
# browser/trocar-fonte-sem-bug.js pro motivo).
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

    A pagina abre com o objeto `card` sem `text`, e nesse estado tanto o import
    quanto a moldura automatica quebram. Escolher grupo e pacote e o que a
    interface faz quando alguem entra na aba Frame.
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
    moldura chegam cada um no seu tempo. Entao a saida e amostrar o desenho ate
    ele se repetir.
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

    Casar pelo id do Scryfall garante a mesma arte, edicao e numero que a API
    devolveu. Devolve se precisou mesmo trocar de impressao - trocar a toa
    dispara uma segunda consulta da edicao e o numero do colecionador sai
    duplicado ("187/361/361").
    """
    indice = await page.evaluate(
        "(id) => scryfallCard.findIndex(c => c.id === id)", carta.id
    )
    if indice is None or indice < 0:
        # A impressao exata nao veio na busca por nome do proprio gerador (e
        # raro agora que a busca pede unique='prints', mas ainda pode faltar
        # em carta com nome tratado diferente, tipo art series). Fica a que o
        # importCard() ja aplicou sozinho - forcar um indice arbitrario aqui
        # pode nao ser uma opcao valida do <select> e travar o changeCardIndex().
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

    O gerador ate tenta o MTGPics, mas passando por um proxy de CORS de
    terceiro e so pelo numero da propria impressao. Quem escolhe e confere a
    arte aqui e app.maker.arte; este passo so entrega a imagem pronta.
    """
    data_url = await arte.buscar(carta)
    if data_url is None:
        return False
    await page.evaluate("(src) => uploadArt(src, 'autoFit')", data_url)
    await _esperar_desenho(page)
    return True


async def _aplicar_marca_dagua(page: Page, carta: ScryfallCard) -> None:
    """Precisa rodar depois da moldura: os limites onde a marca d'agua e
    encaixada (card.watermarkBounds) vem do pacote de molduras."""
    marca = _marca_dagua(carta)
    if marca is None:
        return
    imagem, cor = marca
    await page.evaluate(_APLICAR_MARCA_DAGUA, {"imagem": imagem, "cor": cor})
    await _esperar_desenho(page)


async def _redesenhar_texto_final(page: Page) -> None:
    """Ultimo passo antes de salvar: troca a fonte com bug pelo alias sem
    bug (ver FONTE_SEM_BUG) e forca 1 redesenho de fora da cadeia de callback
    do XHR do proprio fetchScryfallData.

    O redesenho por fora resolve um bug diferente: quando a carta importada
    fica no indice 0 (e _selecionar_impressao nao precisa trocar nada),
    changeCardIndex() e chamado so dali de dentro - encadeado direto no
    onreadystatechange do XHR de busca - e o titulo sai com o ultimo glifo
    faltando em moldura tipo "seventh". Chamar drawTextBuffer() de novo, mas
    por fora, numa chamada evaluate() separada, corrige: o layout/canvas
    parece nao estar totalmente assentado ainda enquanto o navegador esta no
    meio do callback do XHR. Usa so drawTextBuffer() e nao changeCardIndex()
    de novo: o segundo reconsultaria /sets e duplicaria o numero do
    colecionador (ver _selecionar_impressao).
    """
    await page.evaluate(_TROCAR_PARA_FONTE_SEM_BUG, FONTE_SEM_BUG)
    await page.evaluate(_AJUSTAR_TITULO)
    await page.evaluate(_AJUSTAR_LINHA_DE_TIPO)
    await page.evaluate(_AJUSTAR_CAIXA_DE_REGRAS)
    await page.evaluate("() => drawTextBuffer()")
    await _esperar_desenho(page)


_APLICAR_NOME_TRADUZIDO = carregar("aplicar-nome-traduzido")


async def _aplicar_nome_traduzido(page: Page, carta: ScryfallCard) -> None:
    """Poe no titulo o nome traduzido montado fora do Scryfall (hoje, o do
    terreno basico sem impressao em portugues)."""
    if carta.lang != "en" or not carta.printed_name:
        return
    await page.evaluate(_APLICAR_NOME_TRADUZIDO, carta.printed_name)


async def _aplicar_moldura(page: Page, carta: ScryfallCard) -> None:
    """Refaz a moldura automatica com a linha de tipo em ingles (ver
    _APLICAR_MOLDURA). Precisa rodar depois do import: e ele que enche
    card.text.type, e a moldura escolhida na abertura da pagina saiu com a
    carta ainda vazia."""
    await page.evaluate(
        _APLICAR_MOLDURA,
        {
            "tipoIngles": carta.type_line or "",
            "regrasIngles": carta.oracle_text or "",
        },
    )
    await _esperar_desenho(page)


async def _esperar_fontes(page: Page) -> None:
    """Espera fonte customizada (molduras antigas usam fonte propria) acabar
    de carregar antes de ler o canvas - evita capturar o desenho a meio
    caminho de uma troca de fonte tardia."""
    await page.evaluate("() => document.fonts.ready")


async def _salvar(page: Page, carta: ScryfallCard, pasta_destino: Path | None, moldura: str) -> Path:
    await _esperar_fontes(page)
    data_url = await page.evaluate("() => cardCanvas.toDataURL('image/png')")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        raise UpstreamError("O canvas nao devolveu uma imagem PNG")

    pasta = pasta_destino or PASTA_CARTAS_AVULSAS
    pasta.mkdir(parents=True, exist_ok=True)
    nome_base = f"{carta.nome_exibido}-{carta.set}-{carta.collector_number}"
    # Moldura diferente da automatica muda a imagem pra mesma impressao - sem
    # o sufixo, gerar de novo com outra moldura sobrescreveria a primeira.
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
    moldura_sugerida() escolher a partir da impressao real. `preferir_arena`
    troca titulo e regras pela traducao do MTG Arena depois do preenchimento
    normal, quando `carta.arena` tiver texto de regras confiavel (ver
    app.cards.arena) - sem efeito quando nao tiver.
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
        # #import-language tem o mesmo onchange="importChanged()" do
        # #importAllPrints (ver comentario abaixo) - mesmo motivo pra evitar
        # select_option() aqui. #autoFrame fica com select_option mesmo: o
        # onchange dele (setAutoFrame -> autoFrame) e trabalho de verdade,
        # carrega o pacote de moldura que a carta precisa.
        await page.evaluate(
            "(lang) => { document.querySelector('#import-language').value = lang; }", carta.lang
        )
        await page.select_option("#autoFrame", moldura)
        # Com todas as impressoes na lista, o gerador casa a arte pela
        # ilustracao da impressao escolhida em vez da primeira que aparecer.
        # Marca via evaluate, nao page.check(): o checkbox tem
        # onchange="importChanged()", que dispara uma busca extra no Scryfall
        # com #import-name vazio (nunca preenchido, ja que a busca de verdade
        # e a nossa, mais abaixo) - so isso media ~4-5s por carta a toa. So o
        # ESTADO marcado importa (quem le e artFromScryfall(), nao o evento).
        await page.evaluate("() => { document.querySelector('#importAllPrints').checked = true; }")

        nome_busca = carta.name.split(" // ")[0]
        # unique='prints' e o que importChanged() passa quando #importAllPrints
        # esta marcado - chamando fetchScryfallData direto (sem passar pela UI)
        # isso nunca acontecia sozinho, e a busca so trazia 1 impressao por nome.
        # Sem todas as impressoes na lista, o id da carta escolhida podia nao
        # estar ali, e o indice de reserva usado antes (0) nem sempre apontava
        # pra uma opcao valida do <select> - o gerador quebrava com
        # "Cannot read properties of undefined (reading 'lang')".
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
                # Impressao em ingles com printed_type_line preenchido so
                # acontece quando alguem montou a traducao por fora - hoje as
                # fichas (app.cards.fichas).
                "tipoTraduzido": (
                    carta.printed_type_line if carta.lang == "en" else None
                ),
                "textoTraduzido": _texto_traduzido(carta),
                "palavrasDeHabilidade": list(palavras_de_habilidade()),
                "arenaId": carta.id if usar_arena else None,
                "arenaNome": carta.arena.nome if usar_arena else None,
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

        # O importCard() ja aplica a primeira impressao sozinho; deixar essa
        # rodada terminar antes de trocar evita corrida na consulta da edicao.
        await _esperar_desenho(page)
        if await _selecionar_impressao(page, carta):
            await _esperar_desenho(page)
        await _aplicar_moldura(page, carta)
        await _aplicar_marca_dagua(page, carta)
        await _aplicar_nome_traduzido(page, carta)
        await _redesenhar_texto_final(page)
        if arte_mtgpics:
            await _aplicar_arte(page, carta)
        return await _salvar(page, carta, pasta_destino, moldura)
    finally:
        await page.context.close()
