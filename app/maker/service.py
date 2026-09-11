"""Automacao do Card Conjurer (Playwright async).

O gerador roda auto-hospedado em vendor/ (ver app.vendor), servido em
localhost, entao nao ha preenchimento campo a campo: da pra chamar as funcoes
globais dele, que ja sabem importar do Scryfall no idioma escolhido, escolher a
moldura e compor as camadas. A imagem sai lida direto do `cardCanvas`.
"""

import asyncio
import base64
import contextlib
import logging
import re
from contextlib import asynccontextmanager
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.async_api import Browser, Page, Route, async_playwright

from app.cards.enums import Layout, Rarity
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
from app.slug import nome_de_arquivo
from app.vendor.server import ServidorCardConjurer

logger = logging.getLogger(__name__)

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
    "Terreno basico sem borda com nome no topo": "TextlessBasicsBorderlessTopo",
    "Saga": "SagaRegular",
    "Caso": "Case",
    "Classe": "Class",
    "Vanguarda": "Vanguard",
    "Aventura": "Adventure",
    "Virada": "Flip",
    "Dividida": "Split",
    "Ficha": "TokenRegular-1",
}

# O caminho de volta: da moldura escolhida pro rotulo que o menu mostra.
NOME_DA_MOLDURA = {codigo: nome for nome, codigo in MOLDURAS.items()}

# Layout cuja moldura propria o autoFrame ja alcanca.
MOLDURA_DO_LAYOUT = {
    Layout.SAGA: "Saga",
    Layout.CASE: "Caso",
    Layout.CLASS: "Classe",
    Layout.VANGUARD: "Vanguarda",
    Layout.ADVENTURE: "Aventura",
    Layout.FLIP: "Virada",
    Layout.SPLIT: "Dividida",
    Layout.TOKEN: "Ficha",
}
MOLDURA_PADRAO = "M15Regular-1"

# O set_type que a Wizards da as colecoes de piada (Unfinity, Unstable). So
# elas imprimem o nome do terreno basico sem borda no topo.
TIPO_DE_COLECAO_DE_PIADA = "funny"


def moldura_sugerida(carta: ScryfallCard) -> str:  # noqa: PLR0911 - um return por familia de moldura
    """Moldura do #autoFrame mais proxima da impressao real.

    O #autoFrame decide sozinho so cor e tipo; a familia de moldura (M15, 8a
    edicao, borderless...) sai da propria impressao no Scryfall
    (frame/border_color/frame_effects/full_art). Quem quiser outra troca depois.
    """
    efeitos = carta.frame_effects or []
    # Antes de tudo: layout com moldura propria reparte a carta de um jeito que
    # nenhuma moldura de carta comum alcanca - faixa de capitulos na lateral,
    # arte de um lado e texto do outro.
    if carta.layout in MOLDURA_DO_LAYOUT:
        return MOLDURAS[MOLDURA_DO_LAYOUT[carta.layout]]
    # Antes das outras: a carta de papel nao tem janela de arte nem caixa de
    # regras, so a borda da cor e o simbolo de mana no canto, e nenhuma moldura
    # de carta comum chega nisso.
    if e_terreno_basico(carta) and carta.full_art:
        # Sem borda vai mais longe: arte na carta inteira, nome na faixa de baixo.
        if carta.border_color == "borderless":
            # Colecao de piada (UNF, UST) imprime o nome no topo. Sao as 20 das 74
            # impressoes sem borda que fazem isso, e o set_type as separa sozinho.
            if carta.set_type == TIPO_DE_COLECAO_DE_PIADA:
                return MOLDURAS["Terreno basico sem borda com nome no topo"]
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


def nome_da_moldura(carta: ScryfallCard) -> str:
    """Como chamar a moldura desta impressao na tela.

    O mesmo criterio de moldura_sugerida, so que devolvendo o rotulo em vez do
    codigo do autoFrame - e' o que separa uma impressao da outra na hora de
    escolher entre varias.
    """
    codigo = moldura_sugerida(carta)
    return NOME_DA_MOLDURA.get(codigo, codigo)


# Rodando local, moldura e simbolo vem do disco; so estes hosts precisam sair
# pra internet.
HOSTS_LIBERADOS = (
    "127.0.0.1",
    "localhost",
    "api.scryfall.com",
    "svgs.scryfall.io",
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

_IMPRESSAO_DIGITAL = carregar("impressao-digital")

_SELECIONAR_IMPRESSAO = carregar("selecionar-impressao")

_IMPORTAR_CARTAS = carregar("importar-cartas")

_APLICAR_MOLDURA = carregar("aplicar-moldura")

_AJUSTAR_TITULO = carregar("ajustar-titulo")

_AJUSTAR_LINHA_DE_TIPO = carregar("ajustar-linha-de-tipo")


_AJUSTAR_CAIXA_DE_REGRAS = carregar("ajustar-caixa-de-regras")


# O simbolo de mana grande na caixa do terreno basico e desenhado como marca
# d'agua, e ela precisa de imagem e cor: com watermarkLeft em 'none' nada e
# pintado, com 'default' sai o svg cru, preto.
#
# As quatro cores medidas sao as das basicas de Modern Horizons 2, iguais entre
# as duas impressoes de cada cor. O branco fica no hex apagado do seletor do
# gerador: na carta impressa o simbolo branco tem a cor da propria caixa e quem
# o separa e a sombra, que a marca d'agua daqui nao desenha.
MARCA_DAGUA_DE_TERRENO = {
    "W": ("/img/watermarks/w.svg", "#b79d58"),
    "U": ("/img/watermarks/u.svg", "#0a6fb2"),
    "B": ("/img/watermarks/b.svg", "#100c08"),
    "R": ("/img/watermarks/r.svg", "#d62436"),
    "G": ("/img/watermarks/g.svg", "#007c46"),
}

_APLICAR_MARCA_DAGUA = carregar("aplicar-marca-dagua")

# Em porcentagem, como o campo do gerador. Ver aplicar-marca-dagua.js: o padrao
# dele e 40, e no terreno basico a carta impressa traz o simbolo quase opaco.
OPACIDADE_DA_MARCA_DAGUA = 100

# Status a partir do qual a resposta do navegador vira aviso no log.
PRIMEIRO_STATUS_DE_ERRO = 400

INTERVALO_AMOSTRA = 0.1
# Tempo sem mudanca que conta como desenho terminado. Medido em tempo, e nao
# em numero de leituras, pra separar de que em quanto em quanto se olha do
# quanto se espera pra ter certeza - com o navegador ocupado as leituras ja
# saem espacadas sozinhas, porque o evaluate espera a thread da pagina.
JANELA_ESTAVEL = 0.5
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


def _custo_de_cor(carta: ScryfallCard) -> str:
    """O custo de mana que o autoFrame le pra escolher a cor da moldura.

    Ficha nao tem custo, e sem ele a Fada azul e o Inseto preto-verde caem na
    moldura de artefato. As cores do Scryfall viram simbolos so pra essa
    leitura; o custo de verdade volta logo depois (ver aplicar-moldura.js).
    """
    # Carta de duas metades traz os dois custos juntos ("{2}{W}{B} // {W}{B}"),
    # e o cardFrameProperties le a barra como simbolo hibrido. So o da frente
    # decide a cor da moldura.
    da_frente = carta.faces[0].mana_cost if carta.card_faces else carta.mana_cost
    if da_frente:
        return da_frente
    return "".join(f"{{{cor}}}" for cor in carta.colors or [])


def _nome_da_metade(face, indice: int) -> str:
    """O nome so desta metade da carta dividida.

    O Scryfall repete o nome combinado nas DUAS faces da carta dividida
    ("Barulho // Confusao" em cada uma), entao o printed_name sozinho nao
    serve.
    """
    partes = face.nome_exibido.split(" // ")
    return partes[indice] if len(partes) > indice else face.nome_exibido


def _custos_das_metades(carta: ScryfallCard) -> list[str] | None:
    """O custo de cada metade da carta dividida, de cima pra baixo.

    Cada metade tem cor propria, e o autoFrame so enxerga um custo de cada vez.
    A de cima e a SEGUNDA face, como a carta impressa mostra.
    """
    if carta.layout != Layout.SPLIT or not carta.card_faces:
        return None
    return [carta.card_faces[1].mana_cost or "", carta.card_faces[0].mana_cost or ""]


def _letra_da_raridade(carta: ScryfallCard) -> str | None:
    """A letra que o rodape leva no lugar da inicial da raridade, ou None.

    O Scryfall chama tudo isso de `common`, mas a carta impressa distingue:
    ficha sai com "T" (TOTP 5), emblema com "E" (TSOS 13) e terreno comum com
    "L" (MH3 308, LCI 397, REX 26). Incomum, rara e mitica seguem a inicial.
    """
    if carta.layout in (Layout.TOKEN, Layout.DOUBLE_FACED_TOKEN):
        return "T"
    if carta.layout == Layout.EMBLEM:
        return "E"
    if carta.rarity == Rarity.COMMON and "land" in (carta.type_line or "").lower():
        return "L"
    return None


def _e_planeswalker(carta: ScryfallCard) -> bool:
    """Planeswalker tem layout "normal" no Scryfall: o que o separa e a linha de
    tipo, e a moldura dele precisa da caixa de lealdade."""
    return "planeswalker" in (carta.type_line or "").lower()


def _texto_traduzido(carta: ScryfallCard) -> str | None:
    """Texto de regras a impor na impressao em ingles, ou None pra deixar o que
    o Scryfall trouxer.

    Terreno basico impoe vazio: o lembrete em ingles do oracle_text nao existe
    na carta de papel. Carta comum sem PT nenhum impoe o texto emprestado de
    uma irma (ver completar_traducao_pos_corte) quando ele existir.
    """
    if carta.lang != "en":
        return None
    if e_terreno_basico(carta):
        return ""
    return carta.printed_text


def _flavor_traduzido(carta: ScryfallCard) -> str | None:
    """Historia a impor na impressao em ingles, ou None pra deixar a do
    Scryfall.

    A impressao em ingles chega com a historia em ingles, e o import le esse
    campo direto. Quando a traducao veio emprestada de uma irma,
    completar_traducao_pos_corte ja trocou o campo pela versao em portugues.
    """
    if carta.lang != "en" or not carta.printed_name:
        return None
    return carta.flavor_text


def _host(url: str) -> str:
    """O host de uma URL http(s), sem a porta."""
    return url.split("/", 3)[2].split(":", 1)[0]


async def _filtrar_rede(rota: Route) -> None:
    """Deixa passar so o servidor local e as fontes de dados e arte."""
    if _host(rota.request.url) in HOSTS_LIBERADOS:
        await rota.continue_()
    else:
        await rota.abort()


@asynccontextmanager
async def navegador():
    """Abre 1 Chromium com o servidor do Card Conjurer no ar.

    Pra carta avulsa; quem gera lote abre uma vez e reusa, que e o gargalo de
    velocidade.
    """
    with ServidorCardConjurer():
        async with async_playwright() as p:
            navegador_aberto = await p.chromium.launch(headless=HEADLESS)
            try:
                yield navegador_aberto
            finally:
                with contextlib.suppress(Exception):
                    await navegador_aberto.close()


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
    relogio = asyncio.get_running_loop().time
    limite = relogio() + TEMPO_LIMITE_DESENHO
    anterior = None
    ultima_mudanca = relogio()
    while relogio() < limite:
        atual = await page.evaluate(_IMPRESSAO_DIGITAL)
        agora = relogio()
        if atual is None or atual != anterior:
            anterior = atual
            ultima_mudanca = agora
        elif agora - ultima_mudanca >= JANELA_ESTAVEL:
            return
        await asyncio.sleep(INTERVALO_AMOSTRA)
    raise UpstreamError(f"O desenho nao estabilizou em {TEMPO_LIMITE_DESENHO:.0f}s")


async def _selecionar_impressao(page: Page, carta: ScryfallCard) -> bool:
    """Escolhe no gerador a mesma impressao que a consulta trouxe.

    Devolve se precisou mesmo trocar: trocar a toa dispara uma segunda consulta
    da edicao e o numero do colecionador sai duplicado ("187/361/361").
    """
    indice = await page.evaluate("(id) => scryfallCard.findIndex(c => c.id === id)", carta.id)
    if indice is None or indice < 0:
        # A impressao exata nao veio na busca do gerador. Fica a que o
        # importCard() aplicou sozinho: um indice arbitrario pode nao ser opcao
        # valida do <select> e travar o changeCardIndex().
        return False
    atual = await page.evaluate("() => Number(document.querySelector('#import-index').value)")
    if indice == atual:
        return False
    await page.evaluate(_SELECIONAR_IMPRESSAO, indice)
    return True


async def _aspecto_da_janela_de_arte(page: Page) -> float | None:
    """Largura/altura da janela onde a moldura encaixa a arte.

    Cada moldura tem a sua (a de saga e alta e estreita, a borderless e a carta
    inteira), e e ela que diz que formato de arte cabe sem sobrar corte.
    """
    return await page.evaluate(
        """() => {
            const b = card.artBounds;
            if (!b || !b.width || !b.height) return null;
            return (b.width * card.width) / (b.height * card.height);
        }"""
    )


async def _aplicar_arte(page: Page, carta: ScryfallCard, *, usar_mtgpics: bool) -> None:
    """Troca a arte que o gerador achou sozinho pela maior disponivel.

    Quem escolhe e confere e o app.maker.arte; aqui a imagem so e entregue.
    """
    # A carta dividida tem duas janelas de arte e o gerador so tem uma fonte:
    # a montagem ja vem com as duas no lugar (ver arte.dividida).
    if carta.layout == Layout.SPLIT:
        data_url = await arte.dividida(carta)
    else:
        data_url = await arte.buscar(
            carta,
            await _aspecto_da_janela_de_arte(page),
            usar_mtgpics=usar_mtgpics,
        )
    if data_url is None:
        raise UpstreamError(f"{carta.nome_exibido}: não foi possível baixar a arte da impressão")
    await page.evaluate("(src) => uploadArt(src, 'autoFit')", data_url)
    await _esperar_desenho(page)


async def _aplicar_marca_dagua(page: Page, carta: ScryfallCard, moldura: str) -> None:
    """Precisa rodar depois da moldura: os limites onde a marca d'agua e
    encaixada (card.watermarkBounds) vem do pacote de molduras."""
    marca = _marca_dagua(carta, moldura)
    if marca is None:
        return
    imagem, cor = marca
    await page.evaluate(
        _APLICAR_MARCA_DAGUA,
        {"imagem": imagem, "cor": cor, "opacidade": OPACIDADE_DA_MARCA_DAGUA},
    )
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


_APLICAR_SAGA = carregar("aplicar-saga")

# Linha de capitulo: os numerais romanos que o bloco cobre, o travessao e o
# texto. "I, II, III — Crie uma ficha..." cobre tres capitulos num bloco so.
_CAPITULO_DE_SAGA = re.compile(r"^([IVX]+(?:,\s*[IVX]+)*)\s*—\s*(.+)$", re.DOTALL)

# O pacote de saga tem quatro blocos de habilidade.
BLOCOS_DE_SAGA = 4


def _capitulos_de_saga(carta: ScryfallCard) -> dict | None:
    """Quebra o texto da saga no lembrete e nos blocos de capitulo.

    Devolve None quando o texto nao esta no formato esperado; ai a carta segue
    com a moldura montada e os blocos vazios, em vez de sair pela metade.
    """
    linhas = [linha for linha in (carta.texto_exibido or "").split("\n") if linha.strip()]
    if not linhas:
        return None
    lembrete = linhas.pop(0) if linhas[0].startswith("(") else ""
    blocos = []
    for linha in linhas[:BLOCOS_DE_SAGA]:
        achado = _CAPITULO_DE_SAGA.match(linha)
        if not achado:
            return None
        blocos.append({"capitulos": len(achado.group(1).split(",")), "texto": achado.group(2)})
    return {"lembrete": lembrete, "blocos": blocos} if blocos else None


async def _aplicar_saga(page: Page, carta: ScryfallCard) -> None:
    """Depois da moldura: os campos de capitulo so existem com o versionSaga.js
    carregado, e quem manda carregar e a moldura de saga."""
    if carta.layout != Layout.SAGA:
        return
    partes = _capitulos_de_saga(carta)
    if partes is None:
        return
    await page.evaluate(_APLICAR_SAGA, partes)
    await _esperar_desenho(page)


_APLICAR_CLASSE = carregar("aplicar-classe")


async def _aplicar_classe(page: Page, carta: ScryfallCard) -> None:
    """Depois da moldura: os campos de altura de nivel so existem com o
    versionClass.js carregado, e quem manda carregar e a moldura de classe."""
    if carta.layout != Layout.CLASS:
        return
    await page.evaluate(_APLICAR_CLASSE)
    await _esperar_desenho(page)


_APLICAR_DIVIDIDA = carregar("aplicar-dividida")


async def _aplicar_dividida(page: Page, carta: ScryfallCard) -> None:
    """Depois da moldura: o import do gerador para na primeira metade, e na
    moldura dividida ate os campos dela mudam de nome (ver aplicar-dividida.js)."""
    if carta.layout != Layout.SPLIT or not carta.card_faces:
        return
    # A metade de cima da carta em pe e a SEGUNDA face, como a impressa mostra.
    de_cima, de_baixo = carta.card_faces[1], carta.card_faces[0]
    await page.evaluate(
        _APLICAR_DIVIDIDA,
        {
            "nome": _nome_da_metade(de_cima, 1),
            "tipo": de_cima.tipo_exibido or "",
            "custo": de_cima.mana_cost or "",
            "regras": de_cima.texto_exibido or "",
            "nome2": _nome_da_metade(de_baixo, 0),
            "tipo2": de_baixo.tipo_exibido or "",
            "custo2": de_baixo.mana_cost or "",
            "regras2": de_baixo.texto_exibido or "",
        },
    )
    await _esperar_desenho(page)


_APLICAR_VIRADA = carregar("aplicar-virada")


async def _aplicar_virada(page: Page, carta: ScryfallCard) -> None:
    """Depois da moldura: o import do gerador para na metade de cima, entao a
    metade virada sai daqui (ver aplicar-virada.js)."""
    if carta.layout != Layout.FLIP or not carta.card_faces:
        return
    virada = carta.card_faces[1]
    await page.evaluate(
        _APLICAR_VIRADA,
        {
            "nome": virada.nome_exibido,
            "tipo": virada.tipo_exibido or "",
            "regras": virada.texto_exibido or "",
            "pt": f"{virada.power}/{virada.toughness}" if virada.power else "",
        },
    )
    await _esperar_desenho(page)


_APLICAR_AVENTURA = carregar("aplicar-aventura")


async def _aplicar_aventura(page: Page, carta: ScryfallCard) -> None:
    """Depois da moldura: o import do gerador para na face da criatura, entao a
    metade da aventura sai daqui (ver aplicar-aventura.js)."""
    if carta.layout != Layout.ADVENTURE or not carta.card_faces:
        return
    aventura = carta.card_faces[1]
    await page.evaluate(
        _APLICAR_AVENTURA,
        {
            "nome": aventura.nome_exibido,
            "tipo": aventura.tipo_exibido or "",
            "custo": aventura.mana_cost or "",
            "regras": aventura.texto_exibido or "",
        },
    )
    await _esperar_desenho(page)


_APLICAR_VANGUARDA = carregar("aplicar-vanguarda")


async def _aplicar_vanguarda(page: Page, carta: ScryfallCard) -> None:
    """Depois da moldura: os campos de mao e vida so existem na de vanguarda."""
    if carta.layout != Layout.VANGUARD:
        return
    await page.evaluate(
        _APLICAR_VANGUARDA,
        {"mao": carta.hand_modifier or "", "vida": carta.life_modifier or ""},
    )
    await _esperar_desenho(page)


_APLICAR_SELO = carregar("aplicar-selo")


async def _aplicar_selo(page: Page, carta: ScryfallCard) -> None:
    """Precisa rodar depois da moldura: a cor do selo e a dela, e sai do
    card.frames que o autoFrame monta."""
    if not carta.security_stamp:
        return
    await page.evaluate(_APLICAR_SELO, {"formato": carta.security_stamp})
    await _esperar_desenho(page)


async def _aplicar_raridade(page: Page, carta: ScryfallCard) -> None:
    """Depois do import: e ele que preenche o campo com a inicial do Scryfall."""
    letra = _letra_da_raridade(carta)
    if letra is None:
        return
    await page.evaluate(
        """(letra) => {
            document.querySelector('#info-rarity').value = letra;
            return bottomInfoEdited();
        }""",
        letra,
    )


_APLICAR_NOME_TRADUZIDO = carregar("aplicar-nome-traduzido")


async def _aplicar_nome_traduzido(page: Page, carta: ScryfallCard, *, preferir_arena: bool) -> None:
    """Poe no titulo o nome traduzido montado fora do Scryfall: o do terreno
    basico sem impressao em portugues e o do MTG Arena."""
    if carta.lang != "en":
        return
    do_arena = carta.arena.nome if preferir_arena and carta.arena else None
    nome = do_arena or carta.printed_name
    if not nome:
        return
    await page.evaluate(_APLICAR_NOME_TRADUZIDO, nome)


async def _aplicar_moldura(page: Page, carta: ScryfallCard, moldura: str) -> None:
    """Refaz a moldura automatica com a linha de tipo em ingles (ver
    _APLICAR_MOLDURA). Depois do import: e ele que enche card.text.type."""
    await page.evaluate(
        "(moldura) => { document.querySelector('#autoFrame').value = moldura; }",
        moldura,
    )
    await page.evaluate(
        _APLICAR_MOLDURA,
        {
            "tipoIngles": carta.type_line or "",
            "regrasIngles": carta.oracle_text or "",
            "custoDeCor": _custo_de_cor(carta),
            "custosDasMetades": _custos_das_metades(carta),
        },
    )
    await _esperar_desenho(page)


async def _esperar_fontes(page: Page) -> None:
    """Espera a fonte customizada carregar antes de ler o canvas - senao a
    captura pega o desenho no meio de uma troca de fonte tardia."""
    await page.evaluate("() => document.fonts.ready")


# Fracao minima do canvas que precisa sair opaca. Uma carta completa fica em
# ~99,9% (so o arredondado dos cantos fica fora); quando o drawCard() do
# gerador aborta no meio, sobra so uma fatia do canvas, bem abaixo disso.
OPACIDADE_MINIMA_DO_CANVAS = 0.9


def _checar_desenho_completo(carta: ScryfallCard, png: bytes) -> None:
    histograma = Image.open(BytesIO(png)).convert("RGBA").getchannel("A").histogram()
    opacos = sum(histograma[11:])
    fracao = opacos / sum(histograma)
    if fracao < OPACIDADE_MINIMA_DO_CANVAS:
        raise UpstreamError(
            f"{carta.nome_exibido}: o canvas saiu {fracao:.0%} pintado, o desenho nao terminou"
        )


async def _salvar(
    page: Page, carta: ScryfallCard, pasta_destino: Path | None, moldura: str
) -> Path:
    await _esperar_fontes(page)
    data_url = await page.evaluate("() => cardCanvas.toDataURL('image/png')")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        raise UpstreamError("O canvas nao devolveu uma imagem PNG")
    conteudo = base64.b64decode(data_url.split(",", 1)[1])
    _checar_desenho_completo(carta, conteudo)

    pasta = pasta_destino or PASTA_CARTAS_AVULSAS
    pasta.mkdir(parents=True, exist_ok=True)
    partes = [carta.nome_exibido, carta.set, carta.collector_number]
    # Sem o sufixo, gerar a mesma impressao noutra moldura sobrescreveria.
    if moldura != moldura_sugerida(carta):
        partes.append(moldura)
    destino = pasta / f"{nome_de_arquivo(*partes)}.png"
    destino.write_bytes(conteudo)
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
    if _e_planeswalker(carta):
        raise BadRequestError(
            f"{carta.nome_exibido} e planeswalker, que pede a moldura com caixa de "
            "lealdade; o gerador aqui monta so a moldura normal e a carta sairia errada"
        )

    if browser is not None:
        return await _preencher(
            browser,
            carta,
            pasta_destino=pasta_destino,
            moldura=moldura,
            arte_mtgpics=arte_mtgpics,
            preferir_arena=preferir_arena,
        )
    async with navegador() as proprio:
        return await _preencher(
            proprio,
            carta,
            pasta_destino=pasta_destino,
            moldura=moldura,
            arte_mtgpics=arte_mtgpics,
            preferir_arena=preferir_arena,
        )


def _logar_requisicao_falha(requisicao, carta: ScryfallCard) -> None:
    """Requisicao que morreu por conta propria, nao a que nos mesmos cortamos.

    O `_filtrar_rede` aborta tudo que nao esta em HOSTS_LIBERADOS, e cada
    aborte desses chega aqui como "requisicao falhou". Logar isso afogaria a
    falha de verdade no meio do bloqueio de rotina.
    """
    if _host(requisicao.url) not in HOSTS_LIBERADOS:
        return
    logger.warning(
        "%s: requisicao falhou - %s (%s)",
        carta.nome_exibido,
        requisicao.url,
        requisicao.failure,
    )


def _diagnosticar(page: Page, carta: ScryfallCard) -> None:
    """Loga erro de JS do gerador - o `drawCard()` do Card Conjurer pode
    abortar no meio (ex: a busca de arte automatica dele, que roda em paralelo
    com a nossa, falhando) sem avisar nada em Python; so o console do
    navegador denuncia."""
    page.on(
        "pageerror",
        lambda erro: logger.warning("%s: erro no gerador - %s", carta.nome_exibido, erro),
    )
    page.on(
        "console",
        lambda msg: (
            logger.warning("%s: console do gerador - %s", carta.nome_exibido, msg.text)
            if msg.type == "error"
            else None
        ),
    )
    page.on("requestfailed", lambda req: _logar_requisicao_falha(req, carta))
    page.on(
        "response",
        lambda resp: (
            logger.warning("%s: %s em %s", carta.nome_exibido, resp.status, resp.url)
            if resp.status >= PRIMEIRO_STATUS_DE_ERRO
            else None
        ),
    )


async def _preencher(
    browser: Browser,
    carta: ScryfallCard,
    *,
    pasta_destino: Path | None,
    moldura: str,
    arte_mtgpics: bool,
    preferir_arena: bool,
) -> Path:
    page = await abrir_pagina(browser)
    _diagnosticar(page, carta)
    try:
        # Escrito por evaluate, nao por select_option: o onchange do
        # #import-language e o mesmo importChanged() do #importAllPrints (ver
        # abaixo). O #autoFrame fica com select_option porque o onchange dele
        # carrega o pacote de moldura, que e trabalho necessario.
        await page.evaluate(
            "(lang) => { document.querySelector('#import-language').value = lang; }", carta.lang
        )
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
        usar_arena = (
            preferir_arena
            and carta.arena is not None
            and bool(carta.arena.nome or carta.arena.texto)
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
                "tipoTraduzido": (carta.printed_type_line if carta.lang == "en" else None),
                "textoTraduzido": _texto_traduzido(carta),
                "flavorTraduzido": _flavor_traduzido(carta),
                "palavrasDeHabilidade": list(await palavras_de_habilidade()),
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
        await _aplicar_moldura(page, carta, moldura)
        await _aplicar_saga(page, carta)
        await _aplicar_classe(page, carta)
        await _aplicar_vanguarda(page, carta)
        await _aplicar_aventura(page, carta)
        await _aplicar_virada(page, carta)
        await _aplicar_dividida(page, carta)
        await _aplicar_selo(page, carta)
        await _aplicar_marca_dagua(page, carta, moldura)
        await _aplicar_nome_traduzido(page, carta, preferir_arena=usar_arena)
        await _aplicar_raridade(page, carta)
        await _redesenhar_texto_final(page)
        await _aplicar_arte(page, carta, usar_mtgpics=arte_mtgpics)
        return await _salvar(page, carta, pasta_destino, moldura)
    finally:
        # Com o navegador ja caido, fechar o contexto estoura - e a excecao do
        # `finally` substituiria a que explica o que deu errado de verdade.
        with contextlib.suppress(Exception):
            await page.context.close()
