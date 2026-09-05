"""Escolha da arte que vai pra carta.

O recorte do Scryfall (art_crop, 626x457) e pequeno demais pra uma carta
gerada em 2010x2814, entao a arte primaria vem do MTGPics.

Tres armadilhas do MTGPics, as tres tratadas aqui:

1. Ele indexa a ilustracao pela edicao onde ela saiu primeiro, nao pela
   reimpressao. Montar a URL com a edicao/numero do Scryfall so acerta quando
   a carta e da edicao original; em reimpressao da 404, e o caminho certo sai
   da pagina da carta.
2. A numeracao dele nem sempre bate com a do Scryfall - XLN 226 e Raging
   Swordtooth num e Hostage Taker no outro -, entao um 200 pode ser a arte de
   outra carta. Quem resolve isso e o <title> da pagina, que traz o nome em
   ingles: so vale a pagina cujo titulo bate com o nome da carta, e quando o
   ref montado erra, a busca por nome do proprio site diz o ref certo.
3. Parte do acervo e a arte de divulgacao, com credito do artista, logo do
   MAGIC ou linha de copyright estampados sobre a ilustracao. Isso sai na
   carta gerada; quem nao quiser gera com --sem-mtgpics e fica no art_crop.

Confirmada a pagina, a assinatura de imagem escolhe entre as varias artes que
um mesmo nome pode ter - ela decide qual ilustracao, nao qual carta.

O art_crop de reserva e o da impressao em INGLES: quando a Wizards nao publicou
a arte localizada, o da impressao em portugues e uma imagem de aviso
("Localized Image Not Available") no lugar da arte.
"""

import base64
import html
import logging
import re
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from app.cards.models import ScryfallCard
from app.config import SCRYFALL_USER_AGENT
from app.slug import slug

logger = logging.getLogger(__name__)

BASE_MTGPICS = "https://www.mtgpics.com"
BASE_SCRYFALL = "https://api.scryfall.com"

TIMEOUT = 25.0
CABECALHOS = {"User-Agent": SCRYFALL_USER_AGENT}

# Cada miniatura da pagina vem colada no id da ilustracao que a abre, e e por
# esse id que se descobre o ilustrador (ver _ilustrador).
_MINIATURA = re.compile(
    r"LoadIllus\('(\d+)'\).*?pics/art_th/([a-z0-9]+)/([0-9a-z_]+)\.jpg", re.DOTALL
)

# Nome do ilustrador na ficha que o load_illus devolve.
_ILUSTRADOR = re.compile(r"href=illus\?art=\d+>([^<]+)<")

# O titulo da pagina de carta vem como "Nome em ingles - mtgpics.com".
_TITULO = re.compile(r"<title>(.*?)\s*-\s*mtgpics\.com</title>", re.IGNORECASE | re.DOTALL)

# Primeiro resultado da busca por nome, no formato card?ref=<edicao><numero>.
_REF_DO_RESULTADO = re.compile(r"card\?ref=([a-z0-9]+)", re.IGNORECASE)


async def buscar(carta: ScryfallCard) -> str | None:
    """Data URL com a maior arte disponivel pra esta impressao, ou None."""
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers=CABECALHOS
    ) as client:
        referencia = await _art_crop_em_ingles(client, carta)
        if referencia is None:
            return None

        arte = await _melhor_do_mtgpics(client, carta, referencia)
        # O MTGPics costuma ter a arte maior, mas nao sempre - em algumas
        # edicoes recentes o que ele guarda e menor que o recorte do Scryfall.
        if arte is None or _pixels(arte) <= _pixels(referencia):
            arte = referencia
        return _data_url(arte)


async def _melhor_do_mtgpics(
    client: httpx.AsyncClient, carta: ScryfallCard, referencia: bytes
) -> bytes | None:
    """A arte do MTGPics que casa com a ilustracao desta impressao.

    Duas conferencias decidem, as duas exatas: o titulo da pagina diz que e
    esta carta e o ilustrador da ficha diz que e esta ilustracao. A segunda e
    o que separa impressao de terreno basico, onde o nome sozinho nao
    distingue nada. A assinatura de imagem so desempata entre artes do mesmo
    ilustrador pra mesma carta.
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

    candidatas = []
    for ident, edicao, numero in _miniaturas(pagina):
        if not await _e_do_ilustrador(client, ident, carta.artist):
            continue
        imagem = await _baixar_imagem(client, _url_da_arte(f"{edicao}/{numero}"))
        if imagem is None:
            continue
        distancia = _distancia(imagem, assinatura_alvo)
        if distancia is not None:
            candidatas.append((distancia, _pixels(imagem), imagem))

    if not candidatas:
        logger.info(
            "%s: nenhuma arte do MTGPics e de %s, usando o art_crop",
            carta.nome_exibido,
            carta.artist,
        )
        return None
    # Menor distancia decide; empate vai pra imagem maior, que costuma ser a
    # versao em resolucao maior da mesma arte.
    return min(candidatas, key=lambda item: (item[0], -item[1]))[2]


def _url_da_arte(caminho: str) -> str:
    return f"{BASE_MTGPICS}/pics/art/{caminho}.jpg"


async def _pagina_da_carta(client: httpx.AsyncClient, carta: ScryfallCard) -> str | None:
    """O HTML da pagina do MTGPics que e mesmo desta carta, ou None.

    O ref montado com a edicao e o numero do Scryfall acerta na maioria das
    cartas, mas nao em todas, porque as duas fontes numeram diferente. Quando
    o titulo da pagina desmente o ref, a busca por nome do site diz o ref
    certo; se nem ela confirmar, o chamador fica no art_crop.
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

    O titulo vem com entidade HTML - "Chandra&#039;s Spitfire" -, entao passa
    pelo unescape antes da comparacao; sem isso toda carta com apostrofo no
    nome era recusada e caia no art_crop.

    A face da frente entra sozinha porque o MTGPics titula carta de duas faces
    so pela primeira.
    """
    achado = _TITULO.search(pagina)
    if achado is None:
        return False
    titulo = slug(html.unescape(achado.group(1)))
    return titulo in {slug(carta.name), slug(carta.name.split("//")[0])}


def _miniaturas(pagina: str) -> list[tuple[str, str, str]]:
    """(id da ilustracao, edicao, numero) de cada arte listada na pagina."""
    return list(dict.fromkeys(_MINIATURA.findall(pagina)))


async def _e_do_ilustrador(client: httpx.AsyncClient, ident: str, artista: str | None) -> bool:
    """Se a ilustracao e de quem o Scryfall credita nesta impressao.

    Carta de varios artistas vem creditada junta no Scryfall ("A & B") e
    separada no MTGPics, por isso basta um nome cair dentro do outro.
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

    Carta que ja veio em ingles usa o art_crop que a consulta trouxe; pra
    impressao em portugues vale uma requisicao a mais, porque o art_crop em
    portugues pode ser a imagem de aviso em vez da arte.
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


def _pixels(imagem: bytes) -> int:
    try:
        largura, altura = Image.open(BytesIO(imagem)).size
    except (UnidentifiedImageError, OSError):
        return 0
    return largura * altura


def _data_url(imagem: bytes) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(imagem).decode()}"


def _distancia(imagem: bytes, assinatura_alvo: int) -> int | None:
    assinatura = _assinatura(imagem)
    if assinatura is None:
        return None
    return (assinatura ^ assinatura_alvo).bit_count()


def _assinatura(imagem: bytes) -> int | None:
    """dHash de 64 bits do quadrado central da imagem.

    O quadrado central existe porque as duas fontes recortam a mesma
    ilustracao em proporcoes diferentes (o Scryfall em 626x457, o MTGPics as
    vezes em 16:9 de papel de parede); comparar a area comum e o que mantem a
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
