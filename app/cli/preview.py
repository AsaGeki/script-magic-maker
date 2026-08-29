"""Preview da carta no terminal.

Serve pra conferir o que veio do Scryfall antes de gastar tempo gerando a
imagem — principalmente se o texto em português é mesmo o esperado.
"""

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.cards.models import FaceBase, ScryfallCard

CORES_POR_RARIDADE = {
    "common": "white",
    "uncommon": "bright_cyan",
    "rare": "yellow",
    "mythic": "dark_orange",
    "special": "magenta",
    "bonus": "magenta",
}


def _face(face: FaceBase) -> Group:
    cabecalho = Table.grid(expand=True)
    cabecalho.add_column(ratio=1)
    cabecalho.add_column(justify="right")
    cabecalho.add_row(Text(face.nome_exibido, style="bold"), Text(face.mana_cost or ""))

    linhas: list[object] = [cabecalho, Text(face.tipo_exibido or "", style="italic")]

    if face.texto_exibido:
        linhas += ["", Text(face.texto_exibido)]
    if face.flavor_text:
        linhas += ["", Text(face.flavor_text, style="dim italic")]

    if face.power is not None and face.toughness is not None:
        rodape = f"{face.power}/{face.toughness}"
    elif face.loyalty is not None:
        rodape = f"Lealdade {face.loyalty}"
    else:
        rodape = ""
    if rodape:
        linhas += ["", Text(rodape, style="bold", justify="right")]

    return Group(*linhas)


def mostrar_carta(carta: ScryfallCard, console: Console | None = None) -> None:
    """Desenha a carta no terminal, uma moldura por face."""
    console = console or Console()
    cor = CORES_POR_RARIDADE.get(carta.rarity, "white")
    idioma = "português" if carta.tem_portugues else f"idioma {carta.lang}"
    # Sigla em vez do nome da edição: nome de coleção longo estoura a moldura e
    # o rich corta a legenda no meio.
    legenda = f"{carta.set.upper()} #{carta.collector_number} · {carta.rarity} · {idioma}"

    for face in carta.faces:
        console.print(
            Panel(
                _face(face),
                title=carta.set_name,
                title_align="left",
                border_style=cor,
                subtitle=legenda,
                expand=False,
            )
        )
