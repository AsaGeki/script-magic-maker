"""Orquestra o fluxo de PDF: repete cada carta pelas copias que o deck pede e
monta as folhas (layout.py). Consumido pelo menu (app.cli.menu), sem nenhum
questionary aqui - so a logica de montagem."""

from pathlib import Path

from PIL import Image

from app.print import layout

ARQUIVO_COPIAS = "copias.txt"


def repetir_por_copias(pares: list[tuple[Path, int]]) -> list[Path]:
    """1 entrada por copia a imprimir, na ordem em que veio."""
    return [caminho for caminho, copias in pares for _ in range(max(1, copias))]


def escrever_copias(pasta: Path, pares: list[tuple[Path, int]]) -> None:
    """Grava quantas copias de cada carta a pasta representa, 1 linha
    `<quantidade> <arquivo>` por carta - permite ao fluxo de PDF aplicar a
    mesma quantidade do deck sem perguntar de novo."""
    linhas = [f"{copias} {caminho.name}" for caminho, copias in pares]
    (pasta / ARQUIVO_COPIAS).write_text("\n".join(linhas) + "\n", encoding="utf-8")


def ler_copias(pasta: Path) -> dict[str, int]:
    """Quantidade de cada arquivo, pelo copias.txt da pasta - vazio se a
    pasta nao tiver 1 (deck gerado antes desse arquivo existir, ou pasta
    montada a mao)."""
    caminho = pasta / ARQUIVO_COPIAS
    if not caminho.is_file():
        return {}
    copias: dict[str, int] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        partes = linha.strip().split(maxsplit=1)
        if len(partes) == 2 and partes[0].isdigit():
            copias[partes[1]] = int(partes[0])
    return copias


def montar_lote(
    caminhos_cartas: list[Path], *, marca_corte: bool = True
) -> list[Image.Image]:
    """Folhas de frente prontas pro pdf.exportar_pdf."""
    return layout.montar_folhas_frente(caminhos_cartas, marca_corte=marca_corte)
