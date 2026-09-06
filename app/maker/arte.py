"""Escolha da arte que vai pra carta.

O art_crop do Scryfall (626x457) e pequeno pra uma carta gerada em 2010x2814,
entao a arte primaria vem do MTGPics. Tres coisas dele exigem cuidado:

1. A ilustracao e indexada pela edicao onde saiu primeiro, nao pela
   reimpressao: a URL montada com edicao/numero do Scryfall da 404 fora da
   edicao original, e o caminho certo sai da pagina da carta.
2. A numeracao nem sempre bate com a do Scryfall, entao um 200 pode ser a arte
   de outra carta. Quem confirma e o <title> da pagina; quando o ref montado
   erra, a busca por nome do site diz o certo.
3. Parte do acervo e arte de divulgacao, com credito e logo estampados sobre a
   ilustracao. Quem nao quiser gera com --sem-mtgpics e fica no art_crop.

O art_crop de reserva e o da impressao em INGLES: sem arte localizada, o da
impressao em portugues e uma imagem de aviso no lugar da arte.
"""

import base64
import html
import logging
import re
from io import BytesIO
from math import log

import httpx
from PIL import Image, ImageChops, UnidentifiedImageError

from app.cards.models import ScryfallCard
from app.config import SCRYFALL_USER_AGENT
from app.slug import slug

logger = logging.getLogger(__name__)

BASE_MTGPICS = "https://www.mtgpics.com"
BASE_SCRYFALL = "https://api.scryfall.com"

TIMEOUT = 25.0
CABECALHOS = {"User-Agent": SCRYFALL_USER_AGENT}

# Cada miniatura vem colada no id da ilustracao, que e por onde se chega ao
# ilustrador.
_MINIATURA = re.compile(
    r"LoadIllus\('(\d+)'\).*?pics/art_th/([a-z0-9]+)/([0-9a-z_]+)\.jpg", re.DOTALL
)

# Nome do ilustrador na ficha que o load_illus devolve.
_ILUSTRADOR = re.compile(r"href=illus\?art=\d+>([^<]+)<")

# O titulo da pagina de carta vem como "Nome em ingles - mtgpics.com".
_TITULO = re.compile(r"<title>(.*?)\s*-\s*mtgpics\.com</title>", re.IGNORECASE | re.DOTALL)

# Primeiro resultado da busca por nome, no formato card?ref=<edicao><numero>.
_REF_DO_RESULTADO = re.compile(r"card\?ref=([a-z0-9]+)", re.IGNORECASE)


async def buscar(carta: ScryfallCard, aspecto_da_janela: float | None = None) -> str | None:
    """Data URL com a melhor arte disponivel pra esta impressao, ou None.

    `aspecto_da_janela` e largura/altura da janela de arte da moldura escolhida.
    Com ele, uma arte de formato muito diferente perde pro art_crop mesmo sendo
    maior: o gerador preenche a janela e corta o resto, entao arte torta vira
    arte cortada.
    """
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers=CABECALHOS
    ) as client:
        referencia = await _art_crop_em_ingles(client, carta)
        if referencia is None:
            return None

        arte = await _melhor_do_mtgpics(client, carta, referencia)
        if arte is not None:
            arte = _sem_carimbo(arte)
        if arte is None or not _vale_a_pena(arte, referencia, aspecto_da_janela, carta):
            arte = referencia
        return _data_url(arte)


# Quanto o formato do MTGPics pode se afastar do da janela, alem do que o
# art_crop ja se afasta, antes de perder pra ele. Em log, entao 0.25 e um lado
# ~28% fora do esperado: abaixo disso o corte tira pouco e a arte do MTGPics
# ainda compensa por trazer varias vezes mais pixels.
FOLGA_DE_ASPECTO = 0.25


def _aspecto(imagem: bytes) -> float | None:
    try:
        aberta = Image.open(BytesIO(imagem))
    except (UnidentifiedImageError, OSError):
        return None
    return aberta.width / aberta.height if aberta.height else None


def _distancia_do_aspecto(imagem: bytes, janela: float) -> float | None:
    """O quanto o formato da imagem se afasta do da janela, sem lado preferido:
    metade e o dobro da largura pesam igual."""
    aspecto = _aspecto(imagem)
    if aspecto is None or aspecto <= 0:
        return None
    return abs(log(aspecto / janela))


def _vale_a_pena(
    arte: bytes, referencia: bytes, janela: float | None, carta: ScryfallCard
) -> bool:
    """Se a arte do MTGPics ganha do art_crop pra esta moldura."""
    if janela is not None:
        do_mtgpics = _distancia_do_aspecto(arte, janela)
        do_scryfall = _distancia_do_aspecto(referencia, janela)
        if (
            do_mtgpics is not None
            and do_scryfall is not None
            and do_mtgpics > do_scryfall + FOLGA_DE_ASPECTO
        ):
            logger.info(
                "%s: arte do MTGPics no formato errado pra esta moldura "
                "(%.2f contra %.2f do art_crop), ficando no art_crop",
                carta.nome_exibido,
                do_mtgpics,
                do_scryfall,
            )
            return False
    # O MTGPics costuma ter a arte maior, mas nao sempre - em algumas edicoes
    # recentes o que ele guarda e menor que o recorte do Scryfall.
    return _pixels(arte) > _pixels(referencia)


# Onde a moldura dividida abre as duas janelas de arte, medido na carta gerada.
# A de cima e a segunda metade, como a carta impressa mostra.
JANELAS_DA_DIVIDIDA = (
    {"x": 0.1592, "y": 0.0544, "largura": 0.3702, "altura": 0.3866},
    {"x": 0.1592, "y": 0.5107, "largura": 0.3702, "altura": 0.3870},
)

# Proporcao da carta gerada, so pra montar a imagem no tamanho certo.
LARGURA_DA_CARTA = 2010
ALTURA_DA_CARTA = 2814


async def dividida(carta: ScryfallCard) -> str | None:
    """Data URL com as DUAS artes da carta dividida, ja nas janelas.

    O gerador so tem uma fonte de arte, e a carta dividida tem duas janelas: a
    saida e uma imagem do tamanho da carta com cada arte no lugar dela, que
    entra como arte unica e aparece pelas duas janelas.

    As duas artes vem do art_crop, que na carta dividida traz as duas lado a
    lado e deitadas - nem o MTGPics nem as faces do Scryfall trazem separadas.
    """
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers=CABECALHOS
    ) as client:
        recorte = await _art_crop_em_ingles(client, carta)
    if recorte is None:
        return None
    try:
        inteira = Image.open(BytesIO(recorte)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None

    meio = inteira.width // 2
    # A da direita e a metade de cima da carta em pe.
    metades = (
        inteira.crop((meio, 0, inteira.width, inteira.height)),
        inteira.crop((0, 0, meio, inteira.height)),
    )
    montagem = Image.new("RGB", (LARGURA_DA_CARTA, ALTURA_DA_CARTA), "black")
    for metade, janela in zip(metades, JANELAS_DA_DIVIDIDA, strict=True):
        largura = round(janela["largura"] * LARGURA_DA_CARTA)
        altura = round(janela["altura"] * ALTURA_DA_CARTA)
        # A arte esta deitada como a carta se le; em pe ela gira junto do texto.
        deitada = metade.transpose(Image.Transpose.ROTATE_90)
        montagem.paste(
            deitada.resize((largura, altura)),
            (round(janela["x"] * LARGURA_DA_CARTA), round(janela["y"] * ALTURA_DA_CARTA)),
        )
    saida = BytesIO()
    montagem.save(saida, format="JPEG", quality=92)
    return _data_url(saida.getvalue())


async def _melhor_do_mtgpics(
    client: httpx.AsyncClient, carta: ScryfallCard, referencia: bytes
) -> bytes | None:
    """A arte do MTGPics que casa com a ilustracao desta impressao.

    O titulo da pagina confirma a carta e a miniatura numerada como a impressao
    a identifica sozinha. Sem essa, o ilustrador da ficha separa as ilustracoes
    entre si - o que importa em terreno basico, onde o nome nao distingue nada -
    e a assinatura de imagem desempata o que sobrar.
    """
    assinatura_alvo = _assinatura(referencia)
    if assinatura_alvo is None:
        return None

    pagina = await _pagina_da_carta(client, carta)
    if pagina is None:
        logger.info(
            "%s: o MTGPics nao confirmou a carta, usando o art_crop", carta.nome_exibido
        )
        return None

    miniaturas = _miniaturas(pagina)
    # Confirmada a pagina, edicao e numero identificam a impressao sozinhos - e
    # o unico criterio exato quando a carta tem varias artes.
    desta_impressao = (carta.set.lower(), carta.collector_number.zfill(3).lower())
    candidatas = []
    for ident, edicao, numero in miniaturas:
        e_desta = (edicao.lower(), numero.lower()) == desta_impressao
        # O ilustrador so decide o que a numeracao nao decidiu. Cobrar dele a
        # miniatura da propria impressao, ou a unica da pagina, perde arte por
        # divergencia de grafia e por credito errado no MTGPics.
        precisa_do_ilustrador = not e_desta and len(miniaturas) > 1
        if precisa_do_ilustrador and not await _e_do_ilustrador(client, ident, carta.artist):
            continue
        imagem = await _baixar_imagem(client, _url_da_arte(f"{edicao}/{numero}"))
        if imagem is None:
            continue
        distancia = _distancia(imagem, assinatura_alvo)
        if distancia is None:
            continue
        semelhanca = _semelhanca_de_cor(imagem, referencia)
        if semelhanca < SEMELHANCA_MINIMA:
            logger.info(
                "%s: a arte %s/%s do MTGPics tem outra paleta (%.2f), e outra "
                "ilustracao",
                carta.nome_exibido,
                edicao,
                numero,
                semelhanca,
            )
            continue
        # O sufixo "_N" marca outra resolucao do mesmo numero, nao outra
        # ilustracao: o grupo e o numero sem ele.
        grupo = (edicao.lower(), numero.lower().split("_")[0])
        candidatas.append((grupo, 0 if e_desta else 1, distancia, _pixels(imagem), imagem))

    if not candidatas:
        logger.info(
            "%s: nenhuma arte do MTGPics e de %s, usando o art_crop",
            carta.nome_exibido,
            carta.artist,
        )
        return None
    # A da propria impressao vem primeiro; sem ela decide a menor distancia do
    # grupo. Dentro do grupo vencedor vale a imagem maior: reduzir a mesma arte
    # mexe na assinatura o bastante pra versao pequena parecer mais parecida.
    def _peso(grupo: tuple[str, str]) -> tuple[int, int]:
        do_grupo = [c for c in candidatas if c[0] == grupo]
        return (min(c[1] for c in do_grupo), min(c[2] for c in do_grupo))

    melhor = min({c[0] for c in candidatas}, key=_peso)
    return max((c for c in candidatas if c[0] == melhor), key=lambda c: c[3])[4]


def _url_da_arte(caminho: str) -> str:
    return f"{BASE_MTGPICS}/pics/art/{caminho}.jpg"


async def _pagina_da_carta(client: httpx.AsyncClient, carta: ScryfallCard) -> str | None:
    """O HTML da pagina do MTGPics que e mesmo desta carta, ou None.

    O ref montado com edicao e numero do Scryfall acerta na maioria, mas as
    duas fontes numeram diferente. Quando o titulo desmente o ref, a busca por
    nome do site diz o certo; sem confirmacao, o chamador fica no art_crop.
    """
    montado = f"{carta.set}{carta.collector_number.zfill(3)}"
    pagina = await _pagina_do_ref(client, montado)
    if pagina is not None and _e_a_carta(pagina, carta):
        return pagina

    achado = await _ref_por_nome(client, carta.name)
    if achado is None or achado == montado:
        return None
    pagina = await _pagina_do_ref(client, achado)
    if pagina is not None and _e_a_carta(pagina, carta):
        logger.info(
            "%s: %s#%s no MTGPics e outra carta, seguindo pelo ref %s",
            carta.nome_exibido,
            carta.set.upper(),
            carta.collector_number,
            achado,
        )
        return pagina
    return None


async def _pagina_do_ref(client: httpx.AsyncClient, ref: str) -> str | None:
    try:
        resposta = await client.get(f"{BASE_MTGPICS}/card", params={"ref": ref})
    except httpx.HTTPError:
        return None
    return resposta.text if resposta.status_code == 200 else None


async def _ref_por_nome(client: httpx.AsyncClient, nome: str) -> str | None:
    """O ref do primeiro resultado da busca por nome do MTGPics."""
    try:
        resposta = await client.post(
            f"{BASE_MTGPICS}/results.php",
            params={"zbob": 1},
            data={"cardtitle_search": nome},
        )
    except httpx.HTTPError:
        return None
    if resposta.status_code != 200:
        return None
    achado = _REF_DO_RESULTADO.search(resposta.text)
    return achado.group(1).lower() if achado else None


def _e_a_carta(pagina: str, carta: ScryfallCard) -> bool:
    """Se o titulo da pagina nomeia esta carta.

    O titulo vem com entidade HTML ("Chandra&#039;s Spitfire"), por isso o
    unescape. Carta de duas faces as vezes e titulada so pela primeira, as
    vezes pelas duas com barra simples ("Command Tower/Command Tower") - as
    duas formas contam.
    """
    achado = _TITULO.search(pagina)
    if achado is None:
        return False
    titulo = html.unescape(achado.group(1))
    da_pagina = {slug(titulo), slug(titulo.split("/")[0])}
    da_carta = {slug(carta.name), slug(carta.name.split("//")[0])}
    return bool(da_pagina & da_carta)


def _miniaturas(pagina: str) -> list[tuple[str, str, str]]:
    """(id da ilustracao, edicao, numero) de cada arte listada na pagina."""
    return list(dict.fromkeys(_MINIATURA.findall(pagina)))


async def _e_do_ilustrador(client: httpx.AsyncClient, ident: str, artista: str | None) -> bool:
    """Se a ilustracao e de quem o Scryfall credita nesta impressao.

    Carta de varios artistas vem junta no Scryfall ("A & B") e separada no
    MTGPics, por isso basta um nome cair dentro do outro.
    """
    if not artista:
        return False
    try:
        resposta = await client.get(f"{BASE_MTGPICS}/load_illus", params={"i": ident})
    except httpx.HTTPError:
        return False
    if resposta.status_code != 200:
        return False
    achado = _ILUSTRADOR.search(resposta.text)
    if achado is None:
        return False
    do_site, do_scryfall = slug(achado.group(1)), slug(artista)
    return do_site in do_scryfall or do_scryfall in do_site


async def _art_crop_em_ingles(
    client: httpx.AsyncClient, carta: ScryfallCard
) -> bytes | None:
    """O art_crop da impressao em ingles - serve de reserva e de gabarito.

    Impressao em portugues paga uma requisicao a mais porque o art_crop dela
    pode ser a imagem de aviso em vez da arte.
    """
    url = carta.art_crop
    if carta.lang != "en":
        try:
            resposta = await client.get(
                f"{BASE_SCRYFALL}/cards/{carta.set}/{carta.collector_number}/en"
            )
            if resposta.status_code == 200:
                url = (resposta.json().get("image_uris") or {}).get("art_crop") or url
        except httpx.HTTPError:
            pass
    if not url:
        return None
    return await _baixar_imagem(client, url)


async def _baixar_imagem(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        resposta = await client.get(url)
    except httpx.HTTPError:
        return None
    if resposta.status_code != 200:
        return None
    if not resposta.headers.get("content-type", "").startswith("image/"):
        return None
    return resposta.content


# Parte do acervo do MTGPics e arte de divulgacao, com o logo da Magic, a linha
# de copyright ou o nome do artista impressos numa faixa no rodape (ver o
# cabecalho deste modulo). O texto rende mais borda vertical que pintura, e e
# esse pico no rodape que denuncia o carimbo.
#
# O pico diz SE ha carimbo, nao onde ele comeca: sobre a arte o texto rende so
# 1,3 a 2 vezes a mediana, e a faixa nao tem contorno limpo pra seguir. Por isso
# a faixa descartada e fixa, dimensionada pelo maior carimbo visto.
#
# O limiar erra dos dois lados - carimbo discreto passa, arte com detalhe fino
# no rodape e cortada a toa -, mas cortar a toa custa pouco: a arte do MTGPics e
# mais aberta que o recorte que aparece na carta.
LARGURA_DO_PERFIL = 512
LIMIAR_DE_CARIMBO = 1.7
FRACAO_DO_CARIMBO = 0.15


def _perfil_de_bordas(imagem: Image.Image) -> list[float]:
    """Bordas verticais somadas por linha, com a imagem normalizada na largura."""
    cinza = imagem.convert("L")
    cinza = cinza.resize((LARGURA_DO_PERFIL, int(LARGURA_DO_PERFIL * cinza.height / cinza.width)))
    bordas = ImageChops.difference(cinza, ImageChops.offset(cinza, 1, 0))
    dados = list(bordas.getdata())
    return [
        sum(dados[y * LARGURA_DO_PERFIL : (y + 1) * LARGURA_DO_PERFIL]) / LARGURA_DO_PERFIL
        for y in range(bordas.height)
    ]


def _sem_carimbo(imagem: bytes) -> bytes:
    """A mesma arte sem a faixa de rodape, quando ela parece um carimbo."""
    try:
        aberta = Image.open(BytesIO(imagem))
        aberta.load()
    except (UnidentifiedImageError, OSError):
        return imagem

    perfil = _perfil_de_bordas(aberta)
    altura = len(perfil)
    normal = sorted(perfil)[altura // 2] or 1.0
    faixa = perfil[int(altura * (1 - FRACAO_DO_CARIMBO)) :]
    if max(faixa, default=0) < normal * LIMIAR_DE_CARIMBO:
        return imagem

    sobra = int(aberta.height * (1 - FRACAO_DO_CARIMBO))
    cortada = aberta.convert("RGB").crop((0, 0, aberta.width, sobra))
    saida = BytesIO()
    cortada.save(saida, format="JPEG", quality=92)
    return saida.getvalue()


def _pixels(imagem: bytes) -> int:
    try:
        largura, altura = Image.open(BytesIO(imagem)).size
    except (UnidentifiedImageError, OSError):
        return 0
    return largura * altura


def _data_url(imagem: bytes) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(imagem).decode()}"


# Quanto as paletas precisam se sobrepor pra serem a mesma ilustracao. Medido
# no acervo: a arte errada da M15 #279 fica em 0.37 e a mais folgada das certas
# em 0.70. O dHash nao serve de piso aqui - ele poe arte certa em 28 bits e a
# errada em 32.
SEMELHANCA_MINIMA = 0.55

# Lado da miniatura e quantas faixas por canal no histograma.
_LADO_DO_HISTOGRAMA = 32
_FAIXAS_POR_CANAL = 4


def _semelhanca_de_cor(imagem: bytes, referencia: bytes) -> float:
    """Quanto as duas imagens dividem a mesma paleta, de 0 a 1.

    Recorte e resolucao diferentes mexem pouco na distribuicao de cor, entao
    isso separa "mesma ilustracao, outro corte" de "outra ilustracao" - que e
    justamente o que a assinatura de estrutura nao separa.
    """
    de_um, do_outro = _histograma(imagem), _histograma(referencia)
    if de_um is None or do_outro is None:
        return 1.0
    return sum(min(a, b) for a, b in zip(de_um, do_outro, strict=True))


def _histograma(imagem: bytes) -> list[float] | None:
    try:
        aberta = Image.open(BytesIO(imagem)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None
    aberta = aberta.resize((_LADO_DO_HISTOGRAMA, _LADO_DO_HISTOGRAMA))
    deslocamento = 8 - (_FAIXAS_POR_CANAL.bit_length() - 1)
    faixas = [0] * (_FAIXAS_POR_CANAL**3)
    for vermelho, verde, azul in aberta.getdata():
        indice = (vermelho >> deslocamento) * _FAIXAS_POR_CANAL**2
        indice += (verde >> deslocamento) * _FAIXAS_POR_CANAL
        indice += azul >> deslocamento
        faixas[indice] += 1
    total = sum(faixas)
    return [quantidade / total for quantidade in faixas] if total else None


def _distancia(imagem: bytes, assinatura_alvo: int) -> int | None:
    assinatura = _assinatura(imagem)
    if assinatura is None:
        return None
    return (assinatura ^ assinatura_alvo).bit_count()


def _assinatura(imagem: bytes) -> int | None:
    """dHash de 64 bits do quadrado central da imagem.

    O quadrado central existe porque as duas fontes recortam a mesma
    ilustracao em proporcoes diferentes: comparar a area comum e o que mantem a
    mesma arte perto e arte diferente longe.
    """
    try:
        imagem_aberta = Image.open(BytesIO(imagem)).convert("L")
    except (UnidentifiedImageError, OSError):
        return None

    largura, altura = imagem_aberta.size
    lado = min(largura, altura)
    quadrado = imagem_aberta.crop(
        (
            (largura - lado) // 2,
            (altura - lado) // 2,
            (largura + lado) // 2,
            (altura + lado) // 2,
        )
    )
    pixels = list(quadrado.resize((9, 8), Image.LANCZOS).getdata())

    bits = 0
    for linha in range(8):
        for coluna in range(8):
            esquerda = pixels[linha * 9 + coluna]
            direita = pixels[linha * 9 + coluna + 1]
            bits = (bits << 1) | int(esquerda > direita)
    return bits
