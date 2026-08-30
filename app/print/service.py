"""Orquestra o fluxo de PDF: repete cada carta pelas copias que o deck pede e
monta as folhas (layout.py). Consumido pelo menu (app.cli.menu), sem nenhum
questionary aqui - so a logica de montagem."""

from pathlib import Path

from PIL import Image

from app.print import layout


def repetir_por_copias(pares: list[tuple[Path, int]]) -> list[Path]:
    """1 entrada por copia a imprimir, na ordem em que veio."""
    return [caminho for caminho, copias in pares for _ in range(max(1, copias))]


def montar_lote(
    caminhos_cartas: list[Path], *, marca_corte: bool = True
) -> list[Image.Image]:
    """Folhas de frente prontas pro pdf.exportar_pdf."""
    return layout.montar_folhas_frente(caminhos_cartas, marca_corte=marca_corte)
