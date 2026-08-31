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
from app.config import (
    CARDCONJURER_URL,
    HEADLESS,
    OUTPUT_DIR,
)
from app.errors import BadRequestError, UpstreamError
from app.maker import arte
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
    if carta.border_color == "borderless":
        return MOLDURAS["Borderless"]
    if "etched" in efeitos:
        return MOLDURAS["Etched"]
    if carta.full_art:
        return MOLDURAS["Full art (fiel)"]
    if "extendedart" in efeitos:
        return MOLDURAS["Arte estendida"]
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

# Amostra reduzida do canvas, usada so pra saber se o desenho parou de mudar.
_IMPRESSAO_DIGITAL = """() => {
    if (typeof cardCanvas === 'undefined' || !cardCanvas.width) { return null; }
    const mini = document.createElement('canvas');
    mini.width = 32;
    mini.height = 44;
    mini.getContext('2d').drawImage(cardCanvas, 0, 0, mini.width, mini.height);
    return mini.toDataURL();
}"""

_SELECIONAR_IMPRESSAO = """(i) => {
    document.querySelector('#import-index').value = String(i);
    changeCardIndex();
}"""

# importCard() do proprio site so cria <option> quando card.type_line e
# verdadeiro - e processScryfallCard() faz `card.type_line = card.printed_type_line`
# e `card.oracle_text = card.printed_text`, os dois sem fallback nenhum pro
# ingles. Quando o Scryfall tem uma impressao pt parcial (nome traduzido,
# type_line/oracle_text ainda null - o mesmo problema de dado incompleto
# documentado em app.cards.models), a carta some do dropdown em silencio e
# trava o resto do fluxo (type_line vazio) ou sai com a caixa de texto em
# branco (oracle_text vazio) - os dois corrigidos aqui do mesmo jeito.
#
# Tambem e aqui, e nao depois via override, que a traducao do Arena entra
# (quando pedida): fetchScryfallData ja roda processScryfallCard() antes de
# chamar este callback, entao name/oracle_text/flavor_text aqui sao os campos
# FINAIS que changeCardIndex() vai ler. Patchar antes de importCard() faz o
# proprio site aplicar curlyQuotes, itailico de reminder text e formatacao de
# flavor uma vez so - a mesma coisa que ele faz pra carta com pt de verdade.
_IMPORTAR_CARTAS = """(args) => {
    const { nome, idAlvo, tipoDeReserva, textoDeReserva, tipoTraduzido, arenaId, arenaNome, arenaTexto, arenaFlavor } = args;
    fetchScryfallData(nome, (cards) => {
        cards.forEach((c) => {
            if (!c.type_line || c.type_line === 'Card') {
                c.type_line = tipoDeReserva;
            }
            if (!c.oracle_text) {
                c.oracle_text = textoDeReserva;
            }
            // Linha de tipo traduzida fora do Scryfall (ficha, ver
            // app.cards.fichas): a impressao e em ingles, entao o
            // processScryfallCard() do proprio site nao tem printed_type_line
            // pra aplicar sozinho.
            if (tipoTraduzido && c.id === idAlvo) {
                c.type_line = tipoTraduzido;
            }
            if (arenaId && c.id === arenaId) {
                c.name = arenaNome;
                if (arenaTexto) c.oracle_text = arenaTexto;
                if (arenaFlavor) c.flavor_text = arenaFlavor;
            }
        });
        // importCard() desenha a impressao do indice 0 sozinho. Colocando a
        // impressao que queremos ja na frente, ele acerta de primeira - sem
        // isso, desenhava a errada e so depois _selecionar_impressao() (Python)
        // trocava e desenhava tudo de novo, dobrando o tempo de composicao das
        // camadas.
        const indiceAlvo = cards.findIndex((c) => c.id === idAlvo);
        if (indiceAlvo > 0) {
            const [alvo] = cards.splice(indiceAlvo, 1);
            cards.unshift(alvo);
        }
        importCard(cards);
    }, 'prints');
}"""

# autoFrame() e cardFrameProperties() (do proprio gerador) decidem a moldura
# procurando "Land", "Artifact", "Vehicle", "Creature" e "Add" DENTRO da linha
# de tipo e do texto de regras, tudo literal em ingles. Com a carta em
# portugues nenhuma dessas comparacoes bate: terreno vira moldura de artefato,
# veiculo perde a caixa de P/R propria, e a cor do terreno (que sai do "Add"
# do texto) nunca e encontrada. Emprestar a linha de tipo e o texto em ingles
# so durante a chamada resolve todas de uma vez, sem tocar em vendor/.
#
# Restaurar logo depois e seguro porque as funcoes de moldura recebem o texto
# por argumento - o valor ja foi lido quando esta linha roda. E escrever em
# card.text[...].text direto (em vez de passar pela caixa de texto da
# interface) nao dispara textEdited(), que agendaria um autoFrame() novo, com
# o portugues de volta, 500ms depois.
_APLICAR_MOLDURA = """(args) => {
    const tipoPt = card.text.type.text;
    const regrasPt = card.text.rules.text;
    card.text.type.text = args.tipoIngles;
    card.text.rules.text = args.regrasIngles;
    autoFrame();
    card.text.type.text = tipoPt;
    card.text.rules.text = regrasPt;
}"""

# O gerador desenha o custo de mana por cima do titulo, cada um na sua caixa, e
# nao encolhe uma por causa da outra - em ingles os nomes cabem, em portugues
# nao (pior na moldura Seventh, de titulo maior). Encurtar a caixa do titulo
# ate onde o custo comeca faz o proprio writeText() reduzir a fonte ate caber.
#
# A conta do avanco por simbolo e a mesma do writeText(): largura do simbolo
# 0.78 do corpo da fonte, mais o espacamento dos dois lados.
_AJUSTAR_TITULO = """() => {
    const titulo = card.text.title;
    const mana = card.text.mana;
    if (!titulo || !mana || !mana.text) { return; }
    const simbolos = (mana.text.match(/{[^}]*}/g) || []).length;
    if (!simbolos) { return; }

    const corpo = card.height * (mana.size || 0.038);
    const espacamento = corpo * 0.04 + card.width * (mana.manaSpacing || 0);
    const larguraDoCusto = simbolos * (corpo * 0.78 + espacamento * 2);
    const inicioDoCusto = card.width * ((mana.x || 0) + mana.width) - larguraDoCusto;
    const folga = card.width * 0.012;
    const fimDoTitulo = card.width * (titulo.x + titulo.width);
    if (fimDoTitulo > inicioDoCusto - folga) {
        titulo.width = (inicioDoCusto - folga) / card.width - titulo.x;
    }
}"""

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

# A cor entra antes da imagem: uploadWatermark() so reposiciona no onload, e
# watermarkLeftColor() ja redesenha com o que estiver carregado.
_APLICAR_MARCA_DAGUA = """(args) => {
    document.querySelector('#watermark-left').value = args.cor;
    watermarkLeftColor(args.cor);
    uploadWatermark(args.imagem, 'resetWatermark');
}"""

INTERVALO_AMOSTRA = 0.3
AMOSTRAS_IGUAIS = 3  # leituras seguidas sem mudanca = desenho terminou
TEMPO_LIMITE_DESENHO = 45.0
TEMPO_LIMITE_ELEMENTO = 30_000  # milissegundos, como o Playwright espera


def _e_terreno_basico(carta: ScryfallCard) -> bool:
    return (carta.type_line or "").lower().startswith("basic land")


def _marca_dagua(carta: ScryfallCard) -> tuple[str, str] | None:
    """Imagem e cor da marca d'agua desta carta, ou None pra deixar sem.

    So terreno basico usa por enquanto, e a cor sai do proprio simbolo de mana
    do oracle_text ("({T}: Add {R}.)") - assim nao ha tabela de subtipo pra
    manter. Wastes fica de fora: o gerador nao tem svg de incolor.
    """
    if not _e_terreno_basico(carta):
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
    if _e_terreno_basico(carta):
        return ""
    return carta.texto_exibido or ""


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


# writeText() (motor de texto do proprio site) troca a ultima letra de uma
# palavra por um glifo decorativo (area de uso privado do Unicode) quando a
# fonte do campo e exatamente 'belerenb' e a palavra termina em f/h/m/n/k.
# Esse glifo nao renderiza no Chromium que o Playwright usa - vira caixa
# vazia, mesmo a fonte tendo o glifo certo. E so floreio (nao muda a letra),
# entao registrar a MESMA fonte sob outro nome e trocar o `.font` do campo
# evita o gatilho (literal, `font.endsWith('belerenb')`) sem editar
# vendor/cardconjurer.
FONTE_SEM_BUG = "belerenb-sembug"

_TROCAR_PARA_FONTE_SEM_BUG = f"""() => {{
    Object.values(card.text).forEach((campo) => {{
        if (campo.font === 'belerenb') {{
            campo.font = '{FONTE_SEM_BUG}';
        }}
    }});
}}"""


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
    await page.evaluate(_TROCAR_PARA_FONTE_SEM_BUG)
    await page.evaluate(_AJUSTAR_TITULO)
    await page.evaluate("() => drawTextBuffer()")
    await _esperar_desenho(page)


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
        usar_arena = preferir_arena and carta.arena is not None and carta.arena.texto is not None
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
        await _redesenhar_texto_final(page)
        if arte_mtgpics:
            await _aplicar_arte(page, carta)
        return await _salvar(page, carta, pasta_destino, moldura)
    finally:
        await page.context.close()
