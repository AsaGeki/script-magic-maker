"""Exporta as folhas montadas (ver layout.py) pra um PDF, uma pagina por folha.

Pelo img2pdf, que embute o PNG sem recomprimir: o ponto do projeto e carta em
resolucao de impressao, e recompressao em JPEG comeria justamente isso.
"""

import io
from pathlib import Path

import img2pdf
from PIL import Image

from app.config import OUTPUT_DIR
from app.errors import BadRequestError
from app.print import layout

OUTPUT_PATH = Path(OUTPUT_DIR)


def exportar_pdf(folhas: list[Image.Image], nome_arquivo: str) -> Path:
    if not folhas:
        raise BadRequestError("Nenhuma folha pra exportar")
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    destino = OUTPUT_PATH / nome_arquivo

    paginas: list[bytes] = []
    for folha in folhas:
        buffer = io.BytesIO()
        folha.save(buffer, format="PNG")
        paginas.append(buffer.getvalue())

    tamanho = (
        img2pdf.mm_to_pt(layout.A4_LARGURA_MM),
        img2pdf.mm_to_pt(layout.A4_ALTURA_MM),
    )
    destino.write_bytes(img2pdf.convert(paginas, layout_fun=img2pdf.get_layout_fun(tamanho)))
    return destino
