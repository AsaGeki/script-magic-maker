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
from statistics import median

import httpx
from PIL import Image, ImageChops, ImageOps, ImageStat, UnidentifiedImageError

from app import rede
from app.cards.models import ScryfallCard
from app.slug import slug

logger = logging.getLogger(__name__)

BASE_MTGPICS = "https://www.mtgpics.com"
BASE_SCRYFALL = "https://api.scryfall.com"

TIMEOUT = 25.0

# Tamanho da carta que o gerador desenha. Todo retangulo que vem dele - janela
# de arte, janela da dividida - e fracao disto.
LARGURA_DA_CARTA = 2010
ALTURA_DA_CARTA = 2814

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


async def buscar(
    carta: ScryfallCard,
    janela_de_arte: tuple[float, float, float, float] | None = None,
    *,
    usar_mtgpics: bool = True,
    indice_da_face: int = 0,
) -> str | None:
    """Data URL com a melhor arte disponivel pra esta impressao, ou None.

    `janela_de_arte` e (x, y, largura, altura) de onde a moldura escolhida
    encaixa a arte, em fracao da carta - o `card.artBounds` do gerador. O
    formato dela decide se a arte do MTGPics vale mais que o art_crop, porque o
    gerador preenche a janela e corta o resto; a posicao decide onde a arte e
    cortada (ver `_no_enquadramento_impresso`).

    `indice_da_face` escolhe o lado da carta de duas faces. O MTGPics indexa a
    carta inteira, sem separar as faces, entao so a frente passa por ele; o
    verso fica no art_crop do proprio lado.
    """
    aspecto_da_janela = _aspecto_da_janela(janela_de_arte)
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers=rede.CABECALHOS_DE_ARQUIVO
    ) as client:
        referencia = await _art_crop_em_ingles(client, carta, indice_da_face)
        if referencia is None:
            return None

        arte = None
        if usar_mtgpics and indice_da_face == 0:
            arte = await _melhor_do_mtgpics(client, carta, referencia, aspecto_da_janela)
            if arte is not None:
                arte = _sem_carimbo(arte, referencia)
                do_crop = await _janela_do_art_crop(client, carta, referencia, aspecto_da_janela)
                arte = _no_enquadramento_impresso(
                    arte, referencia, (janela_de_arte, do_crop), carta
                )
        if arte is None or not _vale_a_pena(arte, referencia, aspecto_da_janela, carta):
            # So o art_crop passa pelo corte de moldura impressa: a ilustracao
            # do MTGPics nao tem tipografia de carta nenhuma, e o casamento com
            # o art_crop acima e feito com ele inteiro.
            arte = await _sem_a_moldura_da_colecao(client, referencia, carta)
        return _data_url(arte)


def _aspecto_da_janela(janela: tuple[float, float, float, float] | None) -> float | None:
    """Largura/altura da janela em pixels do canvas, nao em fracao da carta."""
    if janela is None or not janela[3]:
        return None
    return (janela[2] * LARGURA_DA_CARTA) / (janela[3] * ALTURA_DA_CARTA)


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


def _vale_a_pena(arte: bytes, referencia: bytes, janela: float | None, carta: ScryfallCard) -> bool:
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
    # recentes o que ele guarda e menor que o recorte do Scryfall. A conta e em
    # pixel util: o que a janela vai cortar nao chega na carta, e o art_crop
    # perde quase metade dele quando a moldura pede uma janela em pe.
    return _pixels_uteis(arte, janela) > _pixels_uteis(referencia, janela)


# O MTGPics guarda a ilustracao inteira; a carta impressa costuma usar um
# recorte dela, e o art_crop do Scryfall E esse recorte. Achando onde ele mora
# dentro da ilustracao da pra cortar no mesmo lugar, em vez de deixar o
# autoFitArt centralizar a imagem toda.

# Tamanho em que todo casamento e comparado. Fixo de proposito: comparando no
# tamanho de cada candidato, a escala menor venceria so por borrar mais.
COMPARACAO = (48, 36)

# Erro RMS acima disto o casamento nao convence. Medido em 26 cartas de dois
# decks: os casamentos bons ficaram entre 3,6 e 19,6, os absurdos entre 21,4 e
# 50,4.
ERRO_MAXIMO_DO_CASAMENTO = 20.0

# Quanto da ilustracao a regiao achada pode cobrir. Fora disso o casamento
# achou coisa que nao existe - a de "Gishath" dava 11,7 vezes a ilustracao.
COBERTURA_MINIMA = 0.20
COBERTURA_MAXIMA = 1.60

# Acima desta sobreposicao o autoFitArt ja mostra o mesmo pedaco, e recortar so
# jogaria pixel fora.
SOBREPOSICAO_QUE_DISPENSA = 0.85

# Quanto da ilustracao a regiao do art_crop precisa cobrir pra nao sobrar
# sub-regiao nenhuma. Medido em 9 cartas de dois decks: onde o art_crop e a
# ilustracao inteira a cobertura ficou entre 0,950 e 1,000, e onde ele e mesmo um
# pedaco dela (Roiling Vortex, Chandra) ficou em 0,728 e 0,335.
COBERTURA_QUE_DISPENSA = 0.85


def _cobre_a_ilustracao(regiao) -> bool:
    """Se a regiao do art_crop e a ilustracao inteira, fora o que passa da borda."""
    largura = min(regiao[2], 1.0) - max(regiao[0], 0.0)
    altura = min(regiao[3], 1.0) - max(regiao[1], 0.0)
    return largura * altura >= COBERTURA_QUE_DISPENSA


# A busca grossa varre a ilustracao inteira nesta largura; a fina repete numa
# vizinhanca, com mais detalhe.
LARGURA_GROSSA = 120
LARGURA_FINA = 320
FRACOES_DA_BUSCA = [0.30 + 0.05 * passo for passo in range(15)]
PASSO = 2

# Menor lado que ainda diz alguma coisa depois de reduzido.
LADO_MINIMO = 8


def _procurar(dentro, alvo, aspecto: float, largura: int, fracoes, area=None):
    """O retangulo de `dentro` que menos difere de `alvo`, em fracao.

    `alvo` ja vem reduzido a COMPARACAO; cada candidato e reduzido ao mesmo
    tamanho antes de comparar. Devolve (erro, x0, y0, x1, y1).
    """
    escala = largura / dentro.width
    reduzida = dentro.resize((largura, max(1, round(dentro.height * escala))), Image.Resampling.BOX)
    melhor = None
    for fracao in fracoes:
        w = round(reduzida.width * fracao)
        h = round(w / aspecto)
        if w < LADO_MINIMO or h < LADO_MINIMO or w > reduzida.width or h > reduzida.height:
            continue
        if area is None:
            xs = range(0, reduzida.width - w + 1, PASSO)
            ys = range(0, reduzida.height - h + 1, PASSO)
        else:
            fx0, fy0, fx1, fy1 = area
            xs = range(
                max(0, round(fx0 * reduzida.width)),
                min(reduzida.width - w, round(fx1 * reduzida.width)) + 1,
                PASSO,
            )
            ys = range(
                max(0, round(fy0 * reduzida.height)),
                min(reduzida.height - h, round(fy1 * reduzida.height)) + 1,
                PASSO,
            )
        for y in ys:
            for x in xs:
                janela = reduzida.crop((x, y, x + w, y + h)).resize(
                    COMPARACAO, Image.Resampling.BOX
                )
                erro = ImageStat.Stat(ImageChops.difference(janela, alvo)).rms[0]
                if melhor is None or erro < melhor[0]:
                    melhor = (
                        erro,
                        x / reduzida.width,
                        y / reduzida.height,
                        (x + w) / reduzida.width,
                        (y + h) / reduzida.height,
                    )
    return melhor


def _registrar(dentro, procurado):
    """Onde `procurado` cai dentro de `dentro`, em fracao. Grosso e depois fino."""
    alvo = procurado.resize(COMPARACAO, Image.Resampling.BOX)
    aspecto = procurado.width / procurado.height
    grosso = _procurar(dentro, alvo, aspecto, LARGURA_GROSSA, FRACOES_DA_BUSCA)
    if grosso is None:
        return None
    _, x0, y0, x1, _ = grosso
    largura = x1 - x0
    fino = _procurar(
        dentro,
        alvo,
        aspecto,
        LARGURA_FINA,
        [largura * (1 + 0.02 * passo) for passo in range(-3, 4)],
        (max(0.0, x0 - 0.06), max(0.0, y0 - 0.06), x0 + 0.06, y0 + 0.06),
    )
    return fino or grosso


# Largura em que a imagem da carta e varrida atras do topo do art_crop. A
# escala ja e conhecida, entao a busca corre so na vertical e cabe num tamanho
# maior que o da busca grossa.
LARGURA_DA_BUSCA_DO_TOPO = 240


def _topo_do_art_crop(carta_inteira, recorte, largura: float, altura: float) -> float | None:
    """Onde, na altura da carta, o art_crop comeca. Fracao de 0 a 1, ou None.

    A largura e a altura do retangulo ja vem sabidas, e ele e centrado na
    horizontal: sobra procurar a linha de cima.
    """
    escala = LARGURA_DA_BUSCA_DO_TOPO / carta_inteira.width
    reduzida = carta_inteira.resize(
        (LARGURA_DA_BUSCA_DO_TOPO, max(1, round(carta_inteira.height * escala))),
        Image.Resampling.BOX,
    )
    alvo = recorte.resize(COMPARACAO, Image.Resampling.BOX)
    largura_px = max(LADO_MINIMO, round(reduzida.width * largura))
    altura_px = max(LADO_MINIMO, round(reduzida.height * altura))
    if largura_px > reduzida.width or altura_px > reduzida.height:
        return None
    x0 = (reduzida.width - largura_px) // 2
    melhor = None
    for y in range(reduzida.height - altura_px + 1):
        janela = reduzida.crop((x0, y, x0 + largura_px, y + altura_px)).resize(
            COMPARACAO, Image.Resampling.BOX
        )
        erro = ImageStat.Stat(ImageChops.difference(janela, alvo)).rms[0]
        if melhor is None or erro < melhor[0]:
            melhor = (erro, y / reduzida.height)
    if melhor is None or melhor[0] > ERRO_MAXIMO_DO_CASAMENTO:
        return None
    return melhor[1]


def _invertida(regiao):
    """A regiao equivalente no outro espaco.

    Quando quem cabe dentro e a ilustracao, e o art_crop que a contem: o
    retangulo do art_crop no espaco da ilustracao sai daqui, e pode passar de
    0 e 1 porque o art_crop mostra mais do que a ilustracao tem.
    """
    erro, x0, y0, x1, y1 = regiao
    largura = x1 - x0
    altura = y1 - y0
    return (erro, -x0 / largura, -y0 / altura, (1 - x0) / largura, (1 - y0) / altura)


# Quando o erro em cinza passa do limite, a paleta da regiao ainda confirma.
# Medido nas artes dos dois decks: casamento certo com erro alto ficou entre
# 0,90 e 0,94 de semelhanca, e o unico errado, em 0,56.
PALETA_QUE_CONFIRMA = 0.75

# Menor pedaco da ilustracao de onde ainda sai um histograma que diz algo.
FRACAO_MINIMA_DA_REGIAO = 0.02

# Acima disto uma faixa de cor sozinha domina a imagem e a paleta para de
# distinguir um pedaco do outro - qualquer recorte de um fundo chapado casa com
# o art_crop. Medido: as artes de pintura ficaram entre 0,20 e 0,38, e a de
# personagem sobre fundo claro (Zidane, FCA 43), em 0,63.
FAIXA_QUE_DOMINA = 0.50


def _erro_do_casamento(imagem: bytes, referencia: bytes) -> float | None:
    """O quanto o art_crop deixa de casar dentro desta ilustracao, ou None.

    O mesmo numero que o `_regiao_do_recorte` usa pra decidir se o casamento
    convence, devolvido antes de escolher a arte.
    """
    try:
        ilustracao = Image.open(BytesIO(imagem)).convert("L")
        recorte = Image.open(BytesIO(referencia)).convert("L")
    except (UnidentifiedImageError, OSError):
        return None
    erros = [
        achado[0]
        for achado in (_registrar(ilustracao, recorte), _registrar(recorte, ilustracao))
        if achado is not None
    ]
    return min(erros) if erros else None


def _regiao_do_recorte(ilustracao: Image.Image, recorte: Image.Image):
    """Onde o art_crop mora na ilustracao, ou None se o casamento nao convence."""
    em_cinza, recorte_em_cinza = ilustracao.convert("L"), recorte.convert("L")
    dentro = _registrar(em_cinza, recorte_em_cinza)
    fora = _registrar(recorte_em_cinza, em_cinza)
    if dentro is None or fora is None:
        return None
    invertida = _invertida(fora)
    regiao = dentro if dentro[0] <= invertida[0] else invertida
    erro, x0, y0, x1, y1 = regiao
    cobertura = (x1 - x0) * (y1 - y0)
    if not COBERTURA_MINIMA <= cobertura <= COBERTURA_MAXIMA:
        return None
    if erro > ERRO_MAXIMO_DO_CASAMENTO and not _confere_a_paleta(
        ilustracao, recorte, (x0, y0, x1, y1)
    ):
        return None
    return (x0, y0, x1, y1)


def _confere_a_paleta(ilustracao: Image.Image, recorte: Image.Image, regiao) -> bool:
    """Se o pedaco achado tem a paleta do art_crop.

    O MTGPics e o Scryfall as vezes guardam versoes diferentes da mesma
    pintura, com outro contraste; o erro em cinza sobe sem que o alinhamento
    esteja errado, e a distribuicao de cor nao se mexe.
    """
    do_recorte = _histograma(recorte)
    if do_recorte is None or max(do_recorte) > FAIXA_QUE_DOMINA:
        return False
    presa = tuple(max(0.0, min(1.0, valor)) for valor in regiao)
    if (
        presa[2] - presa[0] < FRACAO_MINIMA_DA_REGIAO
        or presa[3] - presa[1] < FRACAO_MINIMA_DA_REGIAO
    ):
        return False
    caixa = (
        round(presa[0] * ilustracao.width),
        round(presa[1] * ilustracao.height),
        round(presa[2] * ilustracao.width),
        round(presa[3] * ilustracao.height),
    )
    return _semelhanca_das_paletas(ilustracao.crop(caixa), recorte) >= PALETA_QUE_CONFIRMA


def _no_aspecto(regiao, aspecto_alvo: float, aspecto_da_imagem: float):
    """A regiao crescida ate o formato pedido, sem sair da imagem.

    Cresce pelo lado que falta e o centro nao sai do lugar: encostar na borda
    encolhe o retangulo, nunca o escorrega. Parte do acervo do MTGPics traz a
    carta inteira colada num canto da ilustracao, e escorregar arrastaria esse
    canto pra dentro da janela.
    """
    x0, y0, x1, y1 = regiao
    largura = x1 - x0
    # Em fracao da imagem, o formato de um retangulo depende do formato dela.
    altura_no_formato = largura / aspecto_alvo * aspecto_da_imagem
    altura = y1 - y0
    if altura_no_formato > altura:
        altura = altura_no_formato
    else:
        largura = altura * aspecto_alvo / aspecto_da_imagem
    # Projetar uma janela grande pode pedir um centro fora da imagem; ali nao ha
    # centro a preservar, e prender na borda e o que sobra.
    centro_x = min(1.0, max(0.0, (x0 + x1) / 2))
    centro_y = min(1.0, max(0.0, (y0 + y1) / 2))
    couber = min(
        1.0,
        2 * min(centro_x, 1 - centro_x) / largura,
        2 * min(centro_y, 1 - centro_y) / altura,
    )
    largura *= couber
    altura *= couber
    return (
        centro_x - largura / 2,
        centro_y - altura / 2,
        centro_x + largura / 2,
        centro_y + altura / 2,
    )


def _janela_do_autofit(aspecto_da_imagem: float, aspecto_da_janela: float):
    """O pedaco da ilustracao que o autoFitArt mostraria: o maior retangulo no
    formato da janela, centrado."""
    if aspecto_da_imagem > aspecto_da_janela:
        largura = aspecto_da_janela / aspecto_da_imagem
        altura = 1.0
    else:
        largura = 1.0
        altura = aspecto_da_imagem / aspecto_da_janela
    return ((1 - largura) / 2, (1 - altura) / 2, (1 + largura) / 2, (1 + altura) / 2)


def _sobreposicao(uma, outra) -> float:
    """Area em comum sobre area total, de 0 a 1."""
    x0 = max(uma[0], outra[0])
    y0 = max(uma[1], outra[1])
    x1 = min(uma[2], outra[2])
    y1 = min(uma[3], outra[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    comum = (x1 - x0) * (y1 - y0)
    total = (
        (uma[2] - uma[0]) * (uma[3] - uma[1])
        + (outra[2] - outra[0]) * (outra[3] - outra[1])
        - comum
    )
    return comum / total if total else 0.0


def _cortar(imagem: Image.Image, regiao) -> bytes:
    """A regiao da imagem, em fracao, salva como JPEG."""
    caixa = (
        round(regiao[0] * imagem.width),
        round(regiao[1] * imagem.height),
        round(regiao[2] * imagem.width),
        round(regiao[3] * imagem.height),
    )
    saida = BytesIO()
    imagem.convert("RGB").crop(caixa).save(saida, format="JPEG", quality=95)
    return saida.getvalue()


def _semelhanca_na_regiao(imagem: bytes, referencia: bytes) -> float | None:
    """A semelhanca de cor medida so onde o art_crop cai dentro da ilustracao.

    Devolve None quando o casamento nao convence - sem ele nao ha regiao comum
    de onde tirar a medida.
    """
    try:
        ilustracao = Image.open(BytesIO(imagem))
        recorte = Image.open(BytesIO(referencia))
    except (UnidentifiedImageError, OSError):
        return None
    if not (ilustracao.height and recorte.height):
        return None
    regiao = _regiao_do_recorte(ilustracao, recorte)
    if regiao is None:
        return None
    return _semelhanca_de_cor(_cortar(ilustracao, regiao), referencia)


def _pela_carta(regiao, do_crop, de_destino):
    """A parte da ilustracao que a janela de destino mostra.

    `regiao` e onde o art_crop caiu dentro da ilustracao e `do_crop` e o
    retangulo da carta que esse art_crop cobre: os dois juntos dizem como a
    carta se projeta sobre a ilustracao. Com a projecao, qualquer outra janela
    da carta - a da moldura sem borda, a do planeswalker - vira um retangulo
    da ilustracao.
    """
    mx0, my0, mx1, my1 = do_crop
    dx, dy, dlargura, daltura = de_destino
    escala_x = (regiao[2] - regiao[0]) / (mx1 - mx0)
    escala_y = (regiao[3] - regiao[1]) / (my1 - my0)
    origem_x = regiao[0] - mx0 * escala_x
    origem_y = regiao[1] - my0 * escala_y
    return (
        origem_x + dx * escala_x,
        origem_y + dy * escala_y,
        origem_x + (dx + dlargura) * escala_x,
        origem_y + (dy + daltura) * escala_y,
    )


def _no_enquadramento_impresso(
    arte: bytes, referencia: bytes, janelas, carta: ScryfallCard
) -> bytes:
    """A ilustracao cortada onde a carta impressa corta, quando da pra saber.

    `janelas` e (a janela da moldura de destino, o retangulo da carta que o
    art_crop cobre); o segundo vem None quando os dois tem o mesmo formato e
    crescer a regiao ate o formato da janela ja basta.

    Devolve a ilustracao intacta sempre que o casamento com o art_crop nao
    convence ou quando o autoFitArt ja mostraria o mesmo pedaco - cortar ali so
    tiraria pixels.
    """
    de_destino, do_crop = janelas
    aspecto_da_janela = _aspecto_da_janela(de_destino)
    if de_destino is None or aspecto_da_janela is None:
        return arte
    try:
        ilustracao = Image.open(BytesIO(arte))
        recorte = Image.open(BytesIO(referencia))
    except (UnidentifiedImageError, OSError):
        return arte
    if not (ilustracao.height and recorte.height):
        return arte
    aspecto_da_imagem = ilustracao.width / ilustracao.height
    regiao = _regiao_do_recorte(ilustracao, recorte)
    # Sem casamento nao ha de onde cortar; com o art_crop cobrindo a ilustracao
    # inteira nao ha sub-regiao pra onde cortar, e projetar assim mesmo fecha o
    # corte em cima da cena - a saga perdia o aro e o laco da arte por 12%.
    if regiao is None or _cobre_a_ilustracao(regiao):
        return arte
    if do_crop is not None:
        regiao = _pela_carta(regiao, do_crop, de_destino)
    alvo = _no_aspecto(regiao, aspecto_da_janela, aspecto_da_imagem)
    sobreposicao = _sobreposicao(alvo, _janela_do_autofit(aspecto_da_imagem, aspecto_da_janela))
    if sobreposicao >= SOBREPOSICAO_QUE_DISPENSA:
        return arte
    logger.info(
        "%s: enquadrando a arte onde a carta impressa corta "
        "(sobreposicao %.2f com o encaixe automatico)",
        carta.nome_exibido,
        sobreposicao,
    )
    return _cortar(ilustracao, alvo)


# Onde a moldura dividida abre as duas janelas de arte, medido na carta gerada.
# A de cima e a segunda metade, como a carta impressa mostra.
JANELAS_DA_DIVIDIDA = (
    {"x": 0.1592, "y": 0.0544, "largura": 0.3702, "altura": 0.3866},
    {"x": 0.1592, "y": 0.5107, "largura": 0.3702, "altura": 0.3870},
)


async def dividida(carta: ScryfallCard) -> str | None:
    """Data URL com as DUAS artes da carta dividida, ja nas janelas.

    O gerador so tem uma fonte de arte, e a carta dividida tem duas janelas: a
    saida e uma imagem do tamanho da carta com cada arte no lugar dela, que
    entra como arte unica e aparece pelas duas janelas.

    As duas artes vem do art_crop, que na carta dividida traz as duas lado a
    lado e deitadas - nem o MTGPics nem as faces do Scryfall trazem separadas.
    """
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers=rede.CABECALHOS_DE_ARQUIVO
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
    client: httpx.AsyncClient,
    carta: ScryfallCard,
    referencia: bytes,
    aspecto_da_janela: float | None = None,
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
        logger.info("%s: o MTGPics nao confirmou a carta, usando o art_crop", carta.nome_exibido)
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
            # A ilustracao cheia de uma carta sem borda mostra muito mais cena
            # que o art_crop, que so traz a janela de arte: comparar as duas
            # inteiras poe paletas de regioes diferentes lado a lado. Onde o
            # casamento acha o art_crop dentro dela, a comparacao volta a ser
            # entre o mesmo pedaco.
            na_regiao = _semelhanca_na_regiao(imagem, referencia)
            if na_regiao is None or na_regiao < SEMELHANCA_MINIMA:
                logger.info(
                    "%s: a arte %s/%s do MTGPics tem outra paleta (%.2f), e outra ilustracao",
                    carta.nome_exibido,
                    edicao,
                    numero,
                    semelhanca,
                )
                continue
            semelhanca = na_regiao
        # O sufixo "_N" marca outra versao do mesmo numero: o grupo ignora ele.
        grupo = (edicao.lower(), numero.lower().split("_")[0])
        candidatas.append(
            (
                grupo,
                0 if e_desta else 1,
                distancia,
                _pixels_uteis(imagem, aspecto_da_janela),
                imagem,
                _erro_do_casamento(imagem, referencia),
            )
        )

    if not candidatas:
        logger.info(
            "%s: nenhuma arte do MTGPics e de %s, usando o art_crop",
            carta.nome_exibido,
            carta.artist,
        )
        return None

    # A da propria impressao vem primeiro; sem ela decide a menor distancia do
    # grupo. Dentro do grupo vencedor vale a que sobrevive maior ao corte da
    # janela: reduzir a mesma arte mexe na assinatura o bastante pra versao
    # pequena parecer mais parecida.
    def _peso(grupo: tuple[str, str]) -> tuple[int, int]:
        do_grupo = [c for c in candidatas if c[0] == grupo]
        return (min(c[1] for c in do_grupo), min(c[2] for c in do_grupo))

    melhor = min({c[0] for c in candidatas}, key=_peso)
    do_grupo = [c for c in candidatas if c[0] == melhor]
    # No grupo cabe tambem o papel de parede da mesma arte, com a mesma paleta
    # e outra composicao. Ganha aquela em que o art_crop cabe dentro; o tamanho
    # so desempata.
    casaram = [c for c in do_grupo if c[5] is not None and c[5] <= ERRO_MAXIMO_DO_CASAMENTO]
    return max(casaram or do_grupo, key=lambda c: c[3])[4]


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
        resposta = await rede.com_retentativa_no_429(
            lambda: client.get(f"{BASE_MTGPICS}/card", params={"ref": ref})
        )
    except httpx.HTTPError:
        return None
    return resposta.text if resposta.status_code == httpx.codes.OK else None


async def _ref_por_nome(client: httpx.AsyncClient, nome: str) -> str | None:
    """O ref do primeiro resultado da busca por nome do MTGPics."""
    try:
        resposta = await rede.com_retentativa_no_429(
            lambda: client.post(
                f"{BASE_MTGPICS}/results.php",
                params={"zbob": 1},
                data={"cardtitle_search": nome},
            )
        )
    except httpx.HTTPError:
        return None
    if resposta.status_code != httpx.codes.OK:
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
        resposta = await rede.com_retentativa_no_429(
            lambda: client.get(f"{BASE_MTGPICS}/load_illus", params={"i": ident})
        )
    except httpx.HTTPError:
        return False
    if resposta.status_code != httpx.codes.OK:
        return False
    achado = _ILUSTRADOR.search(resposta.text)
    if achado is None:
        return False
    do_site, do_scryfall = slug(achado.group(1)), slug(artista)
    return do_site in do_scryfall or do_scryfall in do_site


def _art_crop_do_lado(dados: dict, indice_da_face: int) -> str | None:
    """O art_crop desta face na resposta do Scryfall.

    Carta de duas faces guarda a arte dentro de card_faces; o resto traz uma so,
    no nivel de cima.
    """
    faces = dados.get("card_faces") or []
    de_cima = (dados.get("image_uris") or {}).get("art_crop")
    if indice_da_face < len(faces):
        return ((faces[indice_da_face].get("image_uris") or {}).get("art_crop")) or de_cima
    return de_cima


# Abaixo desta diferenca de formato o art_crop e a janela de destino cobrem o
# mesmo pedaco da carta, e projetar um no outro nao muda o recorte.
DIFERENCA_QUE_DISPENSA_A_PROJECAO = 0.02


async def _janela_do_art_crop(
    client: httpx.AsyncClient,
    carta: ScryfallCard,
    recorte: bytes,
    aspecto_da_janela: float | None,
) -> tuple[float, float, float, float] | None:
    """O retangulo da carta que o art_crop mostra, em (x0, y0, x1, y1).

    O art_crop nao e a ilustracao do artista: e um pedaco da imagem da carta,
    do tamanho da janela de arte da moldura comum. Numa carta sem borda ou de
    planeswalker, onde a moldura escolhida abre uma janela maior, saber que
    pedaco e esse e o que diz onde a arte cai.

    O Scryfall corta os dois da mesma imagem, entao a largura e a altura do
    art_crop divididas pelas do `png` ja dao o tamanho do retangulo, e ele sai
    centrado na horizontal; so o topo e procurado.

    Devolve None quando o art_crop e a janela tem o mesmo formato - ai os dois
    mostram o mesmo pedaco - e quando a imagem da carta nao vem.
    """
    if _mesmo_formato(recorte, aspecto_da_janela):
        return None
    url = (carta.image_uris or {}).get("png")
    if not url:
        return None
    baixada = await _baixar_imagem(client, url)
    return None if baixada is None else _medir_a_janela(baixada, recorte)


def _mesmo_formato(recorte: bytes, aspecto_da_janela: float | None) -> bool:
    """Se o art_crop e a janela de destino cobrem o mesmo pedaco da carta."""
    if aspecto_da_janela is None:
        return True
    aspecto_do_recorte = _aspecto(recorte)
    if aspecto_do_recorte is None:
        return True
    diferenca = abs(aspecto_do_recorte - aspecto_da_janela) / aspecto_da_janela
    return diferenca < DIFERENCA_QUE_DISPENSA_A_PROJECAO


def _medir_a_janela(
    imagem_da_carta: bytes, recorte: bytes
) -> tuple[float, float, float, float] | None:
    """O retangulo do art_crop dentro da imagem da carta, em fracao dela."""
    try:
        carta_inteira = Image.open(BytesIO(imagem_da_carta)).convert("L")
        recortada = Image.open(BytesIO(recorte)).convert("L")
    except (UnidentifiedImageError, OSError):
        return None
    if not (carta_inteira.width and carta_inteira.height):
        return None
    largura = recortada.width / carta_inteira.width
    altura = recortada.height / carta_inteira.height
    topo = _topo_do_art_crop(carta_inteira, recortada, largura, altura)
    if topo is None:
        return None
    return ((1 - largura) / 2, topo, (1 + largura) / 2, topo + altura)


async def _art_crop_em_ingles(
    client: httpx.AsyncClient, carta: ScryfallCard, indice_da_face: int = 0
) -> bytes | None:
    """O art_crop da impressao em ingles - serve de reserva e de gabarito.

    Impressao em portugues paga uma requisicao a mais porque o art_crop dela
    pode ser a imagem de aviso em vez da arte.
    """
    faces = carta.card_faces or []
    url = faces[indice_da_face].art_crop if indice_da_face < len(faces) else carta.art_crop
    url = url or carta.art_crop
    if carta.lang != "en":
        try:
            resposta = await rede.com_retentativa_no_429(
                lambda: client.get(f"{BASE_SCRYFALL}/cards/{carta.set}/{carta.collector_number}/en")
            )
            if resposta.status_code == httpx.codes.OK:
                url = _art_crop_do_lado(resposta.json(), indice_da_face) or url
        except httpx.HTTPError:
            pass
    if not url:
        return None
    return await _baixar_imagem(client, url)


# Quantas vezes uma imagem e pedida de novo quando a conexao cai. Sem isso um
# engasgo de rede deixa a carta sem arte nenhuma: o art_crop e o piso, e nao ha
# outra fonte depois dele.
TENTATIVAS_DE_DOWNLOAD = 3


async def _baixar_imagem(client: httpx.AsyncClient, url: str) -> bytes | None:
    for tentativa in range(TENTATIVAS_DE_DOWNLOAD):
        try:
            resposta = await rede.com_retentativa_no_429(lambda: client.get(url))
        except httpx.HTTPError:
            if tentativa == TENTATIVAS_DE_DOWNLOAD - 1:
                return None
            continue
        if resposta.status_code != httpx.codes.OK:
            return None
        if not resposta.headers.get("content-type", "").startswith("image/"):
            return None
        return resposta.content
    return None


# Parte do acervo do MTGPics e arte de divulgacao, com o logo da Magic, a linha
# de copyright ou o nome do artista impressos numa faixa no rodape (ver o
# cabecalho deste modulo). O texto rende mais borda vertical que pintura, e e
# esse pico no rodape que denuncia o carimbo.
#
# O pico so vale se estiver colado na base: pintura com detalhe fino tambem
# passa do limiar, mas mais acima. Medido nas artes dos decks - carimbo de
# verdade comecou entre 0,906 e 0,977 da altura, e os picos de pintura ficaram
# entre 0,750 e 0,869.
LARGURA_DO_PERFIL = 512
LIMIAR_DE_CARIMBO = 1.7
FAIXA_DO_CARIMBO = 0.12
# O texto desbota nas bordas antes de sumir, entao o corte sobe um pouco.
MARGEM_DO_CARIMBO = 0.01

# Boa parte do acervo nao carimba a faixa inteira: escreve o credito ou o logo
# num canto so, e ali a media da linha toda mal se mexe. O pico do terco da
# ponta denuncia esse, e pede limiar proprio - o terco tem menos pintura pra
# diluir o texto. Medido em 17 artes dos dois decks: arte limpa chegou a 1,99 e
# o canto carimbado comecou em 3,04.
TERCOS_DO_PERFIL = 3
LIMIAR_DE_CARIMBO_NO_CANTO = 2.5

# Carimbo de duas linhas - o endereco do ilustrador em cima, o copyright embaixo
# - so passa do limiar na linha mais grossa, e cortar ali deixa a de cima. Achado
# o pico, o corte sobe enquanto o canto continuar em nivel de texto, pulando a
# entrelinha.
LIMIAR_DE_CONTINUACAO = 1.4
ENTRELINHA_DO_CARIMBO = 0.02


def _bordas_por_linha(imagem: Image.Image) -> list[list[int]]:
    """As bordas verticais de cada linha, com a imagem normalizada na largura."""
    cinza = imagem.convert("L")
    cinza = cinza.resize((LARGURA_DO_PERFIL, int(LARGURA_DO_PERFIL * cinza.height / cinza.width)))
    bordas = ImageChops.difference(cinza, ImageChops.offset(cinza, 1, 0))
    dados = list(bordas.getdata())
    return [
        dados[y * LARGURA_DO_PERFIL : (y + 1) * LARGURA_DO_PERFIL] for y in range(bordas.height)
    ]


def _perfil_de_bordas(imagem: Image.Image) -> list[float]:
    """Bordas verticais somadas por linha, com a imagem normalizada na largura."""
    return [sum(linha) / LARGURA_DO_PERFIL for linha in _bordas_por_linha(imagem)]


def _perfil_dos_cantos(linhas: list[list[int]]) -> list[float]:
    """O maior dos dois tercos das pontas, linha por linha."""
    terco = LARGURA_DO_PERFIL // TERCOS_DO_PERFIL
    return [max(sum(linha[:terco]), sum(linha[-terco:])) / terco for linha in linhas]


def _primeira_linha_do_carimbo(cantos: list[float], limite: float, pico: int, primeira: int) -> int:
    """Subindo do pico, a linha onde o bloco de texto comeca."""
    topo = pico
    salto = max(1, round(len(cantos) * ENTRELINHA_DO_CARIMBO))
    for linha in range(pico - 1, primeira - 1, -1):
        if topo - linha > salto:
            break
        if cantos[linha] >= limite:
            topo = linha
    return topo


def _inicio_do_carimbo(imagem: Image.Image) -> float | None:
    """Onde, na altura da imagem, o carimbo comeca. Fracao, ou None se nao ha."""
    linhas = _bordas_por_linha(imagem)
    altura = len(linhas)
    perfil = [sum(linha) / LARGURA_DO_PERFIL for linha in linhas]
    cantos = _perfil_dos_cantos(linhas)
    normal = sorted(perfil)[altura // 2] or 1.0
    primeira = int(altura * (1 - FAIXA_DO_CARIMBO))
    for linha in range(primeira, altura):
        carimbou = (
            perfil[linha] >= normal * LIMIAR_DE_CARIMBO
            or cantos[linha] >= normal * LIMIAR_DE_CARIMBO_NO_CANTO
        )
        if carimbou:
            topo = _primeira_linha_do_carimbo(
                cantos, normal * LIMIAR_DE_CONTINUACAO, linha, primeira
            )
            return max(0.0, topo / altura - MARGEM_DO_CARIMBO)
    return None


# O perfil de borda acusa a faixa, e o art_crop confirma: carimbo e marca que a
# grafica nao imprimiu, entao a faixa de baixo da ilustracao tem que sair
# diferente da mesma faixa do recorte do Scryfall. As duas entram com o contraste
# normalizado - sem isso o copyright escuro sobre pintura escura quase nao muda a
# conta - e a diferenca vale pela pior celula da grade, porque carimbo pequeno se
# dilui na media da faixa inteira.
#
# Medido em 11 ilustracoes do MTGPics: as 10 com carimbo de verdade ficaram entre
# 46,4 e 147,3 na pior celula, e a rachadura do espelho da `Fabula do Quebrador
# de Espelhos` - que o perfil acusa igual - ficou em 10,7.
FAIXA_DA_CONFERENCIA = (96, 24)
CELULAS_DA_CONFERENCIA = (8, 2)
DIFERENCA_QUE_CONFIRMA_O_CARIMBO = 25.0


def _faixa_normalizada(imagem: Image.Image, de: float) -> Image.Image:
    """A faixa entre `de` e a base, em cinza, no tamanho da conferencia."""
    cortada = imagem.convert("L").crop((0, int(imagem.height * de), imagem.width, imagem.height))
    return ImageOps.autocontrast(cortada.resize(FAIXA_DA_CONFERENCIA))


def _pior_celula(diferenca: Image.Image) -> float:
    largura = FAIXA_DA_CONFERENCIA[0] // CELULAS_DA_CONFERENCIA[0]
    altura = FAIXA_DA_CONFERENCIA[1] // CELULAS_DA_CONFERENCIA[1]
    return max(
        ImageStat.Stat(
            diferenca.crop((x * largura, y * altura, (x + 1) * largura, (y + 1) * altura))
        ).rms[0]
        for x in range(CELULAS_DA_CONFERENCIA[0])
        for y in range(CELULAS_DA_CONFERENCIA[1])
    )


def _o_art_crop_confirma_o_carimbo(
    ilustracao: Image.Image, referencia: bytes, inicio: float
) -> bool:
    """Se a faixa acusada tem marca que a carta impressa nao mostra."""
    try:
        recorte = Image.open(BytesIO(referencia))
        recorte.load()
    except (UnidentifiedImageError, OSError):
        return True
    diferenca = ImageChops.difference(
        _faixa_normalizada(ilustracao, inicio), _faixa_normalizada(recorte, inicio)
    )
    return _pior_celula(diferenca) >= DIFERENCA_QUE_CONFIRMA_O_CARIMBO


def _sem_carimbo(imagem: bytes, referencia: bytes | None = None) -> bytes:
    """A mesma arte sem a faixa de rodape, quando ela parece um carimbo.

    `referencia` e o art_crop da mesma impressao; com ele o corte so acontece
    depois de conferido (ver `_o_art_crop_confirma_o_carimbo`).
    """
    try:
        aberta = Image.open(BytesIO(imagem))
        aberta.load()
    except (UnidentifiedImageError, OSError):
        return imagem

    inicio = _inicio_do_carimbo(aberta)
    if inicio is None:
        return imagem
    if referencia is not None and not _o_art_crop_confirma_o_carimbo(aberta, referencia, inicio):
        logger.info(
            "o rodape a partir de %.3f da altura aparece igual no art_crop, e pintura",
            inicio,
        )
        return imagem
    return _cortar(aberta, (0.0, 0.0, 1.0, inicio))


# Na carta sem borda a arte vai ate a aresta e o nome, a linha de tipo e os
# filetes sao impressos sobre ela - dentro do que o Scryfall recorta como
# art_crop. Com a moldura do gerador por cima, essa tipografia reaparece acima
# da faixa de titulo. Duas medidas separam a moldura impressa da ilustracao:
#
# 1. a aresta: o degrau entre a moldura e a arte e uma reta que atravessa a
#    imagem inteira, coisa que contorno de desenho quase nunca faz;
# 2. a chapa: acima da aresta a grafica imprime sobre fundo liso, e a linha
#    inteira fica na mesma cor.
#
# Medido em 38 art_crops sem borda (22 com moldura impressa, 16 limpos): nenhum
# limpo passa nas duas ao mesmo tempo - a maior aresta limpa, 0,533, vem com
# chapa 0,278, e a maior chapa limpa, 0,393, com aresta 0,316 -, e 15 dos 22 com
# moldura passam. Os 7 que faltam saem como hoje, com a moldura visivel.
ARESTA_DA_MOLDURA_IMPRESSA = 0.40
CHAPA_DA_MOLDURA_IMPRESSA = 0.45

# Degrau de cinza que conta como aresta, e distancia ate a cor do meio da linha
# que ainda conta como a mesma chapa.
DEGRAU_DA_ARESTA = 24
TOM_DA_MESMA_CHAPA = 10

# Onde procurar. As primeiras linhas sao a borda da propria imagem, que quase
# toda carta tem; abaixo de um terco ja e ilustracao em qualquer carta medida.
PRIMEIRA_LINHA_DA_MOLDURA = 0.012
FAIXA_DA_MOLDURA_IMPRESSA = 0.32


def _linhas_em_cinza(imagem: Image.Image) -> list[list[int]]:
    """A imagem em cinza, normalizada na largura, linha a linha."""
    cinza = imagem.convert("L")
    cinza = cinza.resize((LARGURA_DO_PERFIL, int(LARGURA_DO_PERFIL * cinza.height / cinza.width)))
    dados = list(cinza.getdata())
    return [dados[y * LARGURA_DO_PERFIL : (y + 1) * LARGURA_DO_PERFIL] for y in range(cinza.height)]


def _chapa(linha: list[int]) -> float:
    """Quanto da linha fica na mesma cor do meio dela."""
    meio = median(linha)
    return sum(1 for valor in linha if abs(valor - meio) <= TOM_DA_MESMA_CHAPA) / len(linha)


def _fim_da_moldura_impressa(imagem: Image.Image) -> float | None:
    """Onde, na altura, a moldura impressa acaba. Fracao, ou None se nao ha.

    Vale a aresta mais funda que passa nas duas medidas: a moldura pode ter
    nome, linha de tipo e filete, e cortar na primeira deixaria o resto.
    """
    linhas = _linhas_em_cinza(imagem)
    altura = len(linhas)
    chapas = [_chapa(linha) for linha in linhas]
    fim = None
    primeira = max(2, int(altura * PRIMEIRA_LINHA_DA_MOLDURA))
    for y in range(primeira, int(altura * FAIXA_DA_MOLDURA_IMPRESSA)):
        aresta = sum(
            1
            for anterior, atual in zip(linhas[y - 1], linhas[y], strict=True)
            if abs(atual - anterior) >= DEGRAU_DA_ARESTA
        ) / len(linhas[y])
        if aresta < ARESTA_DA_MOLDURA_IMPRESSA:
            continue
        if sum(chapas[:y]) / y < CHAPA_DA_MOLDURA_IMPRESSA:
            continue
        fim = y
    return fim / altura if fim else None


def _sem_moldura_impressa(imagem: bytes, carta: ScryfallCard) -> bytes:
    """O art_crop sem a moldura impressa que ele as vezes traz no topo."""
    try:
        aberta = Image.open(BytesIO(imagem))
        aberta.load()
    except (UnidentifiedImageError, OSError):
        return imagem

    fim = _fim_da_moldura_impressa(aberta)
    if fim is None:
        return imagem
    logger.info(
        "%s: o art_crop traz moldura impressa ate %.3f da altura, cortando ali",
        carta.nome_exibido,
        fim,
    )
    return _cortar(aberta, (0.0, fim, 1.0, 1.0))


# A moldura da colecao sem borda nem sempre e reta. Ela pode ser um arco, um
# chanfro de canto ou um filete curvo, e ai nem a aresta nem a chapa a acham:
# as duas medem a linha inteira, e curva nenhuma atravessa a imagem. O que a
# acha e a repeticao - as outras impressoes da mesma colecao com o mesmo
# acabamento trazem a MESMA moldura sobre outra pintura, entao o pixel que e
# borda em quase todas elas e moldura, e o que muda de uma pra outra e pintura.
#
# Medido em 99 art_crops sem borda de 15 colecoes (75 com moldura impressa, 24
# limpos): o ornamento de canto da `HOB` sai dos quatro lados, o chanfro da
# `SOA` e a faixa de titulo da `SLD` saem do topo, e dos 24 limpos o maior
# corte e de 0,021 da altura.

# Tamanho em que as irmas sao comparadas e o degrau de cinza que conta como
# borda.
LADO_DA_MASCARA = (256, 187)
DEGRAU_DA_MASCARA = 18

# Quantas irmas a mascara pede. Abaixo do minimo duas pinturas parecidas ja
# viram moldura - com 4, a pagina de quadrinho da `MSH` marcava 0,195 da
# largura como se fosse coluna de moldura; acima do maximo cada irma custa uma
# requisicao sem mudar o desenho que sai.
IRMAS_MINIMAS = 5
IRMAS_MAXIMAS = 6

# Em quantas irmas o pixel precisa ser borda pra contar como moldura, e quanto
# da linha (ou da coluna) precisa ser moldura pra ela sair no corte - o maior
# entre o piso fixo e o que a propria imagem marca fora da moldura.
IRMAS_QUE_CONFIRMAM = 0.8
MOLDURA_NA_FAIXA = 0.15
VEZES_O_RUIDO_DA_MASCARA = 2.0

# Ate onde procurar, a partir de cada lado. E tambem o teto do corte: moldura
# que passa disso nao e moldura, e a arte da colecao inteira se parecendo com
# ela mesma - a impressao em CMYK da `SLZ` marcava 0,31 da largura dos dois
# lados, e a pagina de quadrinho da `MSH`, 0,21.
FAIXA_DA_MASCARA = 0.20

# Quanto o formato do art_crop da irma pode se afastar do desta impressao. Fora
# disso as duas nao cobrem o mesmo pedaco da carta, e a moldura de uma cai
# noutro lugar da outra.
FOLGA_DO_FORMATO_DA_IRMA = 0.02

# A busca de cada acabamento, guardada pra que um deck com varias cartas do
# mesmo ciclo pague uma requisicao so. A escolha das irmas e por carta: a
# colecao promocional junta dezenas de molduras diferentes sob o mesmo codigo,
# e o que as separa e a numeracao - o ciclo sai em numeros seguidos.
_CANDIDATAS_DO_ACABAMENTO: dict[tuple[str, str, bool, tuple[str, ...]], list[dict]] = {}

# A mesma irma serve varias cartas do ciclo; baixar de novo so gasta requisicao.
_ART_CROP_BAIXADO: dict[str, bytes | None] = {}

_SO_DIGITOS = re.compile(r"\d+")


def _acabamento(
    edicao: str, borda: str | None, arte_cheia: bool, efeitos: list[str] | None
) -> tuple[str, str, bool, tuple[str, ...]]:
    return (edicao, borda or "", bool(arte_cheia), tuple(sorted(efeitos or [])))


def _numero(collector_number: str) -> int:
    """O numero do colecionador sem o sufixo de acabamento (247★ vira 247)."""
    achado = _SO_DIGITOS.search(collector_number or "")
    return int(achado.group()) if achado else 0


async def _irmas_do_acabamento(
    client: httpx.AsyncClient, carta: ScryfallCard, referencia: bytes
) -> list[bytes]:
    """O art_crop das impressoes vizinhas da colecao com o mesmo acabamento."""
    chave = _acabamento(carta.set, carta.border_color, carta.full_art, carta.frame_effects)
    if chave not in _CANDIDATAS_DO_ACABAMENTO:
        _CANDIDATAS_DO_ACABAMENTO[chave] = await _candidatas_a_irma(client, carta, chave)
    daqui = _numero(carta.collector_number)
    vizinhas = sorted(
        (
            d
            for d in _CANDIDATAS_DO_ACABAMENTO[chave]
            if d.get("collector_number") != carta.collector_number
        ),
        key=lambda d: abs(_numero(d.get("collector_number", "")) - daqui),
    )

    aspecto = _aspecto(referencia)
    baixadas: list[bytes] = []
    for dados in vizinhas:
        if len(baixadas) >= IRMAS_MAXIMAS:
            break
        url = _art_crop_do_lado(dados, 0)
        if not url:
            continue
        if url not in _ART_CROP_BAIXADO:
            _ART_CROP_BAIXADO[url] = await _baixar_imagem(client, url)
        imagem = _ART_CROP_BAIXADO[url]
        if imagem is not None and _mesmo_recorte(imagem, aspecto):
            baixadas.append(imagem)
    return baixadas


async def _candidatas_a_irma(
    client: httpx.AsyncClient,
    carta: ScryfallCard,
    chave: tuple[str, str, bool, tuple[str, ...]],
) -> list[dict]:
    termos = [f"set:{carta.set}"]
    if carta.border_color:
        termos.append(f"border:{carta.border_color}")
    if carta.full_art:
        termos.append("is:fullart")
    try:
        resposta = await rede.com_retentativa_no_429(
            lambda: client.get(
                f"{BASE_SCRYFALL}/cards/search",
                params={"q": " ".join(termos), "order": "set"},
            )
        )
    except httpx.HTTPError:
        return []
    if resposta.status_code != httpx.codes.OK:
        return []
    return [d for d in resposta.json().get("data", []) if _do_mesmo_acabamento(d, chave)]


def _do_mesmo_acabamento(dados: dict, chave: tuple[str, str, bool, tuple[str, ...]]) -> bool:
    return (
        _acabamento(
            dados.get("set", ""),
            dados.get("border_color"),
            dados.get("full_art", False),
            dados.get("frame_effects"),
        )
        == chave
    )


def _mesmo_recorte(imagem: bytes, aspecto: float | None) -> bool:
    """Se a irma recorta o mesmo pedaco da carta que esta impressao."""
    if aspecto is None:
        return False
    da_irma = _aspecto(imagem)
    return da_irma is not None and abs(da_irma - aspecto) / aspecto < FOLGA_DO_FORMATO_DA_IRMA


def _bordas_da_mascara(imagem: bytes) -> list[int] | None:
    """Onde a imagem tem borda, nos dois sentidos, no tamanho da mascara."""
    try:
        aberta = Image.open(BytesIO(imagem)).convert("L").resize(LADO_DA_MASCARA)
    except (UnidentifiedImageError, OSError):
        return None
    juntas = ImageChops.lighter(
        ImageChops.difference(aberta, ImageChops.offset(aberta, 1, 0)),
        ImageChops.difference(aberta, ImageChops.offset(aberta, 0, 1)),
    )
    return [int(valor >= DEGRAU_DA_MASCARA) for valor in juntas.getdata()]


def _mascara_da_moldura(irmas: list[bytes]) -> list[bool] | None:
    """Onde a moldura da colecao cai dentro do art_crop, ou None sem irmas."""
    mapas = [mapa for mapa in (_bordas_da_mascara(irma) for irma in irmas) if mapa is not None]
    if len(mapas) < IRMAS_MINIMAS:
        return None
    largura, altura = LADO_DA_MASCARA
    piso = IRMAS_QUE_CONFIRMAM * len(mapas)
    mascara = [sum(mapa[ponto] for mapa in mapas) >= piso for ponto in range(largura * altura)]
    # O deslocamento e circular: a primeira linha e comparada com a ultima e a
    # primeira coluna com a ultima, entao as duas saem sempre como borda.
    for x in range(largura):
        mascara[x] = False
    for y in range(altura):
        mascara[y * largura] = False
    return mascara


def _ate_onde_a_moldura_vai(perfil: list[float]) -> int:
    """Quantas faixas, contando da ponta, a moldura ocupa.

    O piso e relativo ao proprio perfil: colecao de estilo fechado repete
    textura em toda a imagem, e ai o fundo sozinho ja passa de um piso fixo - o
    papel de jornal da `OTP` marcava 0,16 na base, onde nao ha moldura nenhuma.

    Moldura que chega ao fim da faixa procurada nao acabou de ser medida: o que
    se viu foi moldura do comeco ao fim, e onde ela para ficou fora da conta.
    Cortar no limite da busca seria chutar, entao esse lado sai inteiro.
    """
    ate = int(len(perfil) * FAIXA_DA_MASCARA)
    piso = max(MOLDURA_NA_FAIXA, median(perfil) * VEZES_O_RUIDO_DA_MASCARA)
    fim = 0
    for indice in range(ate):
        if perfil[indice] >= piso:
            fim = indice + 1
    return 0 if fim >= ate else fim


def _janela_sem_a_moldura(mascara: list[bool]) -> tuple[float, float, float, float]:
    """O retangulo do art_crop que a moldura da colecao nao alcanca, em fracao."""
    largura, altura = LADO_DA_MASCARA
    linhas = [sum(mascara[y * largura : (y + 1) * largura]) / largura for y in range(altura)]
    colunas = [
        sum(mascara[y * largura + x] for y in range(altura)) / altura for x in range(largura)
    ]
    return (
        _ate_onde_a_moldura_vai(colunas) / largura,
        _ate_onde_a_moldura_vai(linhas) / altura,
        1 - _ate_onde_a_moldura_vai(colunas[::-1]) / largura,
        1 - _ate_onde_a_moldura_vai(linhas[::-1]) / altura,
    )


async def _sem_a_moldura_da_colecao(
    client: httpx.AsyncClient, imagem: bytes, carta: ScryfallCard
) -> bytes:
    """O art_crop reduzido ao que a moldura da colecao nao cobre.

    So impressao sem borda ou de arte cheia passa por aqui: na carta com borda
    a janela de arte e cercada pela moldura e o recorte nao pega tipografia
    nenhuma.

    As duas medidas se somam. A mascara acha o que a colecao repete - arco,
    chanfro, filete -, e `_sem_moldura_impressa` acha a faixa de titulo, que a
    mascara nao ve: o nome muda de carta pra carta, e o que muda nao e moldura.
    """
    if carta.border_color != "borderless" and not carta.full_art:
        return imagem
    mascara = _mascara_da_moldura(await _irmas_do_acabamento(client, carta, imagem))
    if mascara is not None:
        imagem = _na_janela_da_colecao(imagem, _janela_sem_a_moldura(mascara), carta)
    return _sem_moldura_impressa(imagem, carta)


def _na_janela_da_colecao(
    imagem: bytes, janela: tuple[float, float, float, float], carta: ScryfallCard
) -> bytes:
    if janela == (0.0, 0.0, 1.0, 1.0):
        return imagem
    try:
        aberta = Image.open(BytesIO(imagem))
        aberta.load()
    except (UnidentifiedImageError, OSError):
        return imagem
    logger.info(
        "%s: a moldura da colecao deixa a arte em x %.3f-%.3f e y %.3f-%.3f, cortando ali",
        carta.nome_exibido,
        janela[0],
        janela[2],
        janela[1],
        janela[3],
    )
    return _cortar(aberta, janela)


def _pixels(imagem: bytes) -> int:
    try:
        largura, altura = Image.open(BytesIO(imagem)).size
    except (UnidentifiedImageError, OSError):
        return 0
    return largura * altura


def _pixels_uteis(imagem: bytes, janela: float | None) -> int:
    """Quantos pixels sobram depois do corte que a janela impoe.

    Contar pixel bruto faz o papel de parede 16:9 ganhar da ilustracao no
    formato da carta: ele e maior, mas a janela joga fora o que sobra nas
    laterais.
    """
    try:
        largura, altura = Image.open(BytesIO(imagem)).size
    except (UnidentifiedImageError, OSError):
        return 0
    if janela is None or not altura:
        return largura * altura
    if largura / altura > janela:
        largura = round(altura * janela)
    else:
        altura = round(largura / janela)
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
    try:
        uma = Image.open(BytesIO(imagem))
        outra = Image.open(BytesIO(referencia))
    except (UnidentifiedImageError, OSError):
        return 1.0
    return _semelhanca_das_paletas(uma, outra)


def _semelhanca_das_paletas(uma: Image.Image, outra: Image.Image) -> float:
    de_um, do_outro = _histograma(uma), _histograma(outra)
    if de_um is None or do_outro is None:
        return 1.0
    return sum(min(a, b) for a, b in zip(de_um, do_outro, strict=True))


def _histograma(imagem: Image.Image) -> list[float] | None:
    aberta = imagem.convert("RGB").resize((_LADO_DO_HISTOGRAMA, _LADO_DO_HISTOGRAMA))
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
    pixels = list(quadrado.resize((9, 8), Image.Resampling.LANCZOS).getdata())

    bits = 0
    for linha in range(8):
        for coluna in range(8):
            esquerda = pixels[linha * 9 + coluna]
            direita = pixels[linha * 9 + coluna + 1]
            bits = (bits << 1) | int(esquerda > direita)
    return bits
