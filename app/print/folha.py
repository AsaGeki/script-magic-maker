"""Montagem da folha de impressão.

Nove cartas por página A4, no tamanho físico real (63,5 x 88,9 mm), com marcas
de corte nos cantos pra guiar a guilhotina.

A folha é montada em pixels, na resolução de saída escolhida, e só vira
milímetro na hora de fechar o PDF.
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

# Medidas oficiais em milímetros.
CARTA_MM = (63.5, 88.9)
A4_MM = (210.0, 297.0)
LETTER_MM = (215.9, 279.4)

COLUNAS = 3
LINHAS = 3
POR_FOLHA = COLUNAS * LINHAS

DPI_PADRAO = 600
COR_DA_MARCA = (128, 128, 128)


def _mm_para_px(mm: float, dpi: int) -> int:
    return round(mm / 25.4 * dpi)


@dataclass
class LayoutDaFolha:
    """Onde cada carta cai na página, já em pixels."""

    dpi: int = DPI_PADRAO
    pagina_mm: tuple[float, float] = A4_MM
    marcas_de_corte: bool = True

    @property
    def tamanho_da_pagina(self) -> tuple[int, int]:
        return (
            _mm_para_px(self.pagina_mm[0], self.dpi),
            _mm_para_px(self.pagina_mm[1], self.dpi),
        )

    @property
    def tamanho_da_carta(self) -> tuple[int, int]:
        return (_mm_para_px(CARTA_MM[0], self.dpi), _mm_para_px(CARTA_MM[1], self.dpi))

    @property
    def margem(self) -> tuple[int, int]:
        """Sobra dividida igualmente dos dois lados, centralizando a grade."""
        largura_pagina, altura_pagina = self.tamanho_da_pagina
        largura_carta, altura_carta = self.tamanho_da_carta
        return (
            (largura_pagina - largura_carta * COLUNAS) // 2,
            (altura_pagina - altura_carta * LINHAS) // 2,
        )

    def posicao(self, indice: int) -> tuple[int, int]:
        """Canto superior esquerdo da carta de índice 0 a 8."""
        margem_x, margem_y = self.margem
        largura_carta, altura_carta = self.tamanho_da_carta
        coluna, linha = indice % COLUNAS, indice // COLUNAS
        return (margem_x + coluna * largura_carta, margem_y + linha * altura_carta)


def montar_folha(imagens: list[Path], layout: LayoutDaFolha | None = None) -> Image.Image:
    """Cola até nove cartas numa página. Sobra de espaço fica em branco."""
    layout = layout or LayoutDaFolha()
    folha = Image.new("RGB", layout.tamanho_da_pagina, "white")

    for indice, caminho in enumerate(imagens[:POR_FOLHA]):
        with Image.open(caminho) as carta:
            redimensionada = carta.convert("RGB").resize(
                layout.tamanho_da_carta, Image.LANCZOS
            )
        folha.paste(redimensionada, layout.posicao(indice))

    if layout.marcas_de_corte:
        _desenhar_marcas(folha, layout)
    return folha


def _desenhar_marcas(folha: Image.Image, layout: LayoutDaFolha) -> None:
    """Traços curtos nas bordas, alinhados com as linhas de corte da grade.

    Ficam fora da área das cartas, na margem, pra não sujar a arte.
    """
    desenho = ImageDraw.Draw(folha)
    largura_pagina, altura_pagina = layout.tamanho_da_pagina
    largura_carta, altura_carta = layout.tamanho_da_carta
    margem_x, margem_y = layout.margem
    comprimento = _mm_para_px(3, layout.dpi)
    espessura = max(1, layout.dpi // 300)

    for coluna in range(COLUNAS + 1):
        x = margem_x + coluna * largura_carta
        desenho.line([(x, 0), (x, margem_y - 1)], fill=COR_DA_MARCA, width=espessura)
        desenho.line(
            [(x, altura_pagina - margem_y + 1), (x, altura_pagina)],
            fill=COR_DA_MARCA,
            width=espessura,
        )

    for linha in range(LINHAS + 1):
        y = margem_y + linha * altura_carta
        desenho.line([(0, y), (margem_x - 1, y)], fill=COR_DA_MARCA, width=espessura)
        desenho.line(
            [(largura_pagina - margem_x + 1, y), (largura_pagina, y)],
            fill=COR_DA_MARCA,
            width=espessura,
        )

    # Marca curta também nas divisões internas, encostada nas bordas da grade.
    for coluna in range(1, COLUNAS):
        x = margem_x + coluna * largura_carta
        for y in (margem_y, altura_pagina - margem_y - comprimento):
            desenho.line([(x, y), (x, y + comprimento)], fill=COR_DA_MARCA, width=espessura)
