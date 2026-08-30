"""Preview de carta no terminal antes de confirmar a geracao: ficha (rich
Panel) e a arte de verdade (term-image - desenha via protocolo grafico do
terminal quando suportado, cai pra blocos coloridos sozinho quando nao)."""

import asyncio
import io

import httpx
import questionary
from PIL import Image
from rich.console import Console
from rich.panel import Panel
from term_image.image import AutoImage

from app.cards.models import ScryfallCard
from app.config import SCRYFALL_USER_AGENT

console = Console()


def mostrar_ficha(carta: ScryfallCard) -> None:
    linhas = [f"[bold]{carta.nome_exibido}[/] ({carta.tipo_exibido})"]
    if not carta.traduzida:
        linhas.append("[red]Sem impressao PT - nome/texto em ingles[/]")
    if carta.mana_cost:
        linhas.append(f"Custo: {carta.mana_cost}")
    linhas.append(f"Edicao: {carta.set_name} ({carta.set.upper()}) #{carta.collector_number}")
    linhas.append(f"Raridade: {carta.rarity}")
    if carta.power is not None and carta.toughness is not None:
        linhas.append(f"Poder/Resistencia: {carta.power}/{carta.toughness}")
    if carta.loyalty is not None:
        linhas.append(f"Lealdade: {carta.loyalty}")
    if carta.artist:
        linhas.append(f"Arte: {carta.artist}")
    for face in carta.faces:
        if face.texto_exibido:
            titulo = f"\n[dim]{face.nome_exibido}[/]\n" if carta.card_faces else "\n"
            linhas.append(f"{titulo}{face.texto_exibido}")
        if face.flavor_text:
            linhas.append(f"[italic dim]{face.flavor_text}[/]")
    console.print(
        Panel("\n".join(linhas), title="Carta encontrada", border_style="cyan")
    )
    _mostrar_comparativo_arena(carta)


def _mostrar_comparativo_arena(carta: ScryfallCard) -> None:
    """Compara o impresso (Scryfall) com o do jogo digital (Arena) quando os
    2 existem - divergem por 2 motivos: a carta e pos-corte de traducao (so
    tem no Arena) ou o texto mudou por errata desde que foi impresso."""
    arena = carta.arena
    if arena is None:
        return

    nome_igual = arena.nome == carta.nome_exibido
    texto_igual = arena.texto is None or arena.texto == carta.texto_exibido
    if nome_igual and texto_igual:
        return

    motivo = "carta sem impressao em PT" if not carta.traduzida else "texto mudou por errata"
    linhas = [f"[dim]({motivo})[/]", f"[bold]{arena.nome}[/]"]
    if arena.texto:
        linhas.append(f"\n{arena.texto}")
    else:
        linhas.append("[dim]Regra ainda nao traduzida no Arena - so o nome bateu.[/]")
    if arena.flavor_text:
        linhas.append(f"[italic dim]{arena.flavor_text}[/]")
    console.print(
        Panel(
            "\n".join(linhas),
            title="MTG Arena (nao impresso em papel)",
            border_style="magenta",
        )
    )


async def _baixar_artes(urls: list[str | None]) -> list[bytes | None]:
    """Baixa as artes em paralelo com o nosso User-Agent.

    O `from_url` do term-image usa `requests`, e o Scryfall responde 400 pro
    User-Agent padrao dele - por isso a imagem vem daqui e o term-image so
    desenha o que ja esta em memoria.
    """
    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers={"User-Agent": SCRYFALL_USER_AGENT}
    ) as client:

        async def baixar(url: str | None) -> bytes | None:
            if not url:
                return None
            try:
                resposta = await client.get(url)
            except httpx.HTTPError:
                return None
            return resposta.content if resposta.status_code == 200 else None

        return await asyncio.gather(*(baixar(url) for url in urls))


def _renderizar_imagem(dados: bytes | None, largura: int) -> list[str]:
    """Renderiza 1 arte ja baixada, devolve as linhas prontas (BaseImage tem
    __str__ que devolve o texto renderizado, sem escrever no stdout) - assim da
    pra compor varias lado a lado em vez de so uma por vez."""
    if dados is None:
        return ["[sem arte]"]
    try:
        return str(AutoImage(Image.open(io.BytesIO(dados)), width=largura)).splitlines()
    except Exception as exc:  # noqa: BLE001 - preview e so-o-melhor-esforco, nunca deve travar o fluxo
        return [f"[nao consegui mostrar: {exc}]"]


async def mostrar_impressoes_em_grade(
    impressoes: list[ScryfallCard], *, colunas: int = 3, largura_cada: int = 28
) -> None:
    """Mostra as artes lado a lado (ate `colunas` por linha) em vez de
    empilhadas - evita rolar o terminal pra comparar."""
    artes = await _baixar_artes([c.art_crop for c in impressoes])

    for inicio in range(0, len(impressoes), colunas):
        lote = impressoes[inicio : inicio + colunas]
        print(
            "  ".join(
                f"{inicio + i + 1}. {c.set.upper()} #{c.collector_number}".center(largura_cada)
                for i, c in enumerate(lote)
            )
        )

        blocos = [
            _renderizar_imagem(artes[inicio + i], largura_cada) for i in range(len(lote))
        ]
        altura = max(len(bloco) for bloco in blocos)
        for bloco in blocos:
            bloco.extend([" " * largura_cada] * (altura - len(bloco)))
        for linha in range(altura):
            print("  ".join(bloco[linha] for bloco in blocos))


async def escolher_impressao(impressoes: list[ScryfallCard]) -> ScryfallCard:
    """Se so ha 1 impressao, devolve ela direto. Se ha mais (reimpressao com
    arte alternativa), mostra o preview de cada uma e deixa escolher."""
    if len(impressoes) == 1:
        return impressoes[0]

    console.print(
        f"\n[bold]'{impressoes[0].nome_exibido}' tem {len(impressoes)} impressoes:[/]"
    )
    await mostrar_impressoes_em_grade(impressoes)

    escolha = await questionary.select(
        "Qual impressao usar?",
        choices=[
            questionary.Choice(
                f"{c.set_name} ({c.set.upper()}) #{c.collector_number}"
                f" - {c.artist or 'sem artista'}",
                c,
            )
            for c in impressoes
        ],
    ).ask_async()
    if escolha is None:
        raise KeyboardInterrupt
    return escolha
