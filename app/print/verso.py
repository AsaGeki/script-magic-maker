"""Verso generico de carta - pro lado de tras da folha de impressao duplex.

Toda celula da folha sai identica de proposito: como nenhum verso e diferente
do outro, o registro fino do duplex (a impressora nunca acerta 100% onde a
folha 2 cai sobre a 1) deixa de importar - nao tem "verso errado" possivel, so
"1 verso generico deslocado alguns milimetros", que ainda corta certo.

So linha fina, sem area solida preenchida - o verso oficial de Magic e fundo
marrom solido, que em varias folhas gasta muito mais tinta que uma moldura +
5 circulos entrelacados.
"""

import math

from PIL import Image, ImageDraw

from app.print.layout import CARTA_ALTURA_PX, CARTA_LARGURA_PX, mm_para_px, montar_folha_repetida

COR_LINHA = "black"

MARGEM_EXTERNA_MM = 3
MARGEM_INTERNA_MM = 5
RAIO_CANTO_MM = 2.5
ESPESSURA_EXTERNA_MM = 0.5
ESPESSURA_INTERNA_MM = 0.3

RAIO_CIRCULO_MM = 8
DISTANCIA_CENTRO_MM = 5
ESPESSURA_CIRCULO_MM = 0.3
QUANTIDADE_CIRCULOS = 5


def desenhar_verso() -> Image.Image:
    """Moldura dupla + circulos entrelacados no centro, so contorno."""
    imagem = Image.new("RGB", (CARTA_LARGURA_PX, CARTA_ALTURA_PX), "white")
    desenho = ImageDraw.Draw(imagem)

    externa = mm_para_px(MARGEM_EXTERNA_MM)
    desenho.rounded_rectangle(
        [externa, externa, CARTA_LARGURA_PX - externa, CARTA_ALTURA_PX - externa],
        radius=mm_para_px(RAIO_CANTO_MM),
        outline=COR_LINHA,
        width=mm_para_px(ESPESSURA_EXTERNA_MM),
    )
    interna = mm_para_px(MARGEM_INTERNA_MM)
    desenho.rounded_rectangle(
        [interna, interna, CARTA_LARGURA_PX - interna, CARTA_ALTURA_PX - interna],
        radius=mm_para_px(RAIO_CANTO_MM * 0.7),
        outline=COR_LINHA,
        width=mm_para_px(ESPESSURA_INTERNA_MM),
    )

    centro_x, centro_y = CARTA_LARGURA_PX / 2, CARTA_ALTURA_PX / 2
    raio = mm_para_px(RAIO_CIRCULO_MM)
    distancia = mm_para_px(DISTANCIA_CENTRO_MM)
    espessura = mm_para_px(ESPESSURA_CIRCULO_MM)
    for indice in range(QUANTIDADE_CIRCULOS):
        angulo = math.radians(90 + indice * 360 / QUANTIDADE_CIRCULOS)
        x = centro_x + distancia * math.cos(angulo)
        y = centro_y - distancia * math.sin(angulo)
        desenho.ellipse(
            [x - raio, y - raio, x + raio, y + raio],
            outline=COR_LINHA,
            width=espessura,
        )
    return imagem


def montar_folha() -> Image.Image:
    """1 folha A4 com o verso repetido nas 9 celulas, pronta pro
    print.pdf.exportar_pdf."""
    return montar_folha_repetida(desenhar_verso())
