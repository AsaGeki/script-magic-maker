"""Geração do PDF de impressão.

As folhas montadas viram um PDF com a página no tamanho físico exato, pra
impressora não reescalar nada. O img2pdf embute a imagem sem recomprimir.
"""

import io
from pathlib import Path

import img2pdf

from app.config import settings
from app.errors import ErroDoApp
from app.print.folha import POR_FOLHA, LayoutDaFolha, montar_folha


def paginar(imagens: list[Path]) -> list[list[Path]]:
    """Divide a lista de cartas em grupos de nove."""
    return [imagens[i : i + POR_FOLHA] for i in range(0, len(imagens), POR_FOLHA)]


def repetir_por_quantidade(pares: list[tuple[Path, int]]) -> list[Path]:
    """Uma entrada por cópia a imprimir, na ordem em que veio."""
    return [caminho for caminho, quantidade in pares for _ in range(max(1, quantidade))]


def montar_pdf(
    imagens: list[Path],
    destino: Path | None = None,
    layout: LayoutDaFolha | None = None,
) -> Path:
    """Monta as folhas e fecha o PDF. Devolve o caminho do arquivo."""
    if not imagens:
        raise ErroDoApp("Nenhuma imagem para imprimir.")

    layout = layout or LayoutDaFolha()
    caminho = destino or (settings.output_dir / "impressao.pdf")
    caminho.parent.mkdir(parents=True, exist_ok=True)

    paginas: list[bytes] = []
    for grupo in paginar(imagens):
        buffer = io.BytesIO()
        montar_folha(grupo, layout).save(buffer, format="PNG")
        paginas.append(buffer.getvalue())

    largura_mm, altura_mm = layout.pagina_mm
    tamanho_em_pontos = (img2pdf.mm_to_pt(largura_mm), img2pdf.mm_to_pt(altura_mm))
    caminho.write_bytes(
        img2pdf.convert(paginas, layout_fun=img2pdf.get_layout_fun(tamanho_em_pontos))
    )
    return caminho
