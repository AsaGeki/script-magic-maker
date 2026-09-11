"""Exporta as folhas montadas (ver layout.py) pra um PDF, uma pagina por folha.

Pelo img2pdf, que embute o PNG sem recomprimir: o ponto do projeto e carta em
resolucao de impressao, e recompressao em JPEG comeria justamente isso.

Nada disso fica todo na memoria ao mesmo tempo. Uma folha A4 a 600 DPI ocupa
~104 MB descomprimida, entao cada uma e gravada em arquivo temporario e
liberada assim que sai; o img2pdf monta o PDF lendo esses arquivos e escrevendo
direto no destino.
"""

import tempfile
from collections.abc import Iterable
from pathlib import Path

import img2pdf
from PIL import Image

from app.config import OUTPUT_DIR
from app.errors import BadRequestError
from app.print import layout

OUTPUT_PATH = Path(OUTPUT_DIR)


def exportar_pdf(folhas: Iterable[Image.Image], nome_arquivo: str) -> Path:
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    destino = OUTPUT_PATH / nome_arquivo
    tamanho = (
        img2pdf.mm_to_pt(layout.A4_LARGURA_MM),
        img2pdf.mm_to_pt(layout.A4_ALTURA_MM),
    )

    with tempfile.TemporaryDirectory(prefix="magic-maker-pdf-") as pasta_temporaria:
        paginas = [str(caminho) for caminho in _gravar_paginas(folhas, Path(pasta_temporaria))]
        if not paginas:
            raise BadRequestError("Nenhuma folha pra exportar")
        with destino.open("wb") as saida:
            img2pdf.convert(
                paginas,
                outputstream=saida,
                layout_fun=img2pdf.get_layout_fun(tamanho),
            )
    return destino


def _gravar_paginas(folhas: Iterable[Image.Image], pasta: Path) -> list[Path]:
    """Cada folha em disco, na ordem, e fora da memoria assim que gravada."""
    caminhos: list[Path] = []
    for indice, folha in enumerate(folhas):
        caminho = pasta / f"{indice:04d}.png"
        folha.save(caminho, format="PNG")
        folha.close()
        caminhos.append(caminho)
    return caminhos
