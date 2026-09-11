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

from app import rede
from app.cards.models import ScryfallCard
from app.cards.service import e_terreno_basico
from app.errors import NotFoundError
from app.maker.service import nome_da_moldura

# A arte do preview e so pra olhar; nao vale segurar o menu por muito tempo.
TIMEOUT_DA_ARTE = 20.0

console = Console()


def descrever_impressao(carta: ScryfallCard) -> str:
    """Edicao, ano, moldura e ilustrador numa linha.

    Sao os quatro que fazem duas impressoes da mesma carta serem cartas
    diferentes na mesa: o ano diz de que epoca e' o desenho da moldura, e a
    moldura diz o que o gerador vai desenhar.
    """
    partes = [f"{carta.set.upper()} #{carta.collector_number}"]
    if carta.released_at:
        partes.append(str(carta.released_at.year))
    partes.append(nome_da_moldura(carta))
    if carta.artist:
        partes.append(carta.artist)
    return " · ".join(partes)


def mostrar_ficha(carta: ScryfallCard) -> None:
    linhas = [f"[bold]{carta.nome_exibido}[/] ({carta.tipo_exibido})"]
    if not carta.traduzida:
        linhas.append("[red]Sem impressao PT - nome/texto em ingles[/]")
    if carta.mana_cost:
        linhas.append(f"Custo: {carta.mana_cost}")
    ano = f", {carta.released_at.year}" if carta.released_at else ""
    linhas.append(f"Edicao: {carta.set_name} ({carta.set.upper()}) #{carta.collector_number}{ano}")
    linhas.append(f"Raridade: {carta.rarity}")
    linhas.append(f"Moldura: {nome_da_moldura(carta)}")
    if carta.power is not None and carta.toughness is not None:
        linhas.append(f"Poder/Resistencia: {carta.power}/{carta.toughness}")
    if carta.loyalty is not None:
        linhas.append(f"Lealdade: {carta.loyalty}")
    if carta.artist:
        linhas.append(f"Arte: {carta.artist}")
    # Terreno basico nao imprime texto nenhum: o oracle_text ("T: Add G.") e so
    # a regra do jogo, nunca aparece na carta de papel - mostrar aqui confunde
    # com uma descricao que a carta nao tem.
    terreno_basico = e_terreno_basico(carta)
    for face in carta.faces:
        if face.texto_exibido and not terreno_basico:
            titulo = f"\n[dim]{face.nome_exibido}[/]\n" if carta.card_faces else "\n"
            linhas.append(f"{titulo}{face.texto_exibido}")
        if face.flavor_text:
            linhas.append(f"[italic dim]{face.flavor_text}[/]")
    console.print(Panel("\n".join(linhas), title="Carta encontrada", border_style="cyan"))
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
        timeout=TIMEOUT_DA_ARTE, follow_redirects=True, headers=rede.CABECALHOS_DE_ARQUIVO
    ) as client:

        async def baixar(url: str | None) -> bytes | None:
            if not url:
                return None
            try:
                resposta = await client.get(url)
            except httpx.HTTPError:
                return None
            return resposta.content if resposta.status_code == httpx.codes.OK else None

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
        console.print(
            "  ".join(
                f"{inicio + i + 1}. {c.set.upper()} #{c.collector_number}".center(largura_cada)
                for i, c in enumerate(lote)
            ),
            markup=False,
            highlight=False,
        )

        blocos = [_renderizar_imagem(artes[inicio + i], largura_cada) for i in range(len(lote))]
        altura = max(len(bloco) for bloco in blocos)
        for bloco in blocos:
            bloco.extend([" " * largura_cada] * (altura - len(bloco)))
        for linha in range(altura):
            console.print(
                "  ".join(bloco[linha] for bloco in blocos), markup=False, highlight=False
            )


# Teto de artes desenhadas no terminal. Terreno basico passa de 280
# impressoes; baixar e desenhar todas trava o fluxo por minutos e nao cabe na
# tela. A lista de escolha continua com todas.
MAXIMO_COM_ARTE = 12


async def escolher_impressao(impressoes: list[ScryfallCard]) -> ScryfallCard:
    """Se so ha 1 impressao, devolve ela direto. Se ha mais (reimpressao com
    arte alternativa), mostra o preview de cada uma e deixa escolher."""
    if not impressoes:
        raise NotFoundError("Nenhuma impressao pra escolher")
    if len(impressoes) == 1:
        return impressoes[0]

    console.print(f"\n[bold]'{impressoes[0].nome_exibido}' tem {len(impressoes)} impressoes:[/]")
    com_arte = impressoes[:MAXIMO_COM_ARTE]
    if len(com_arte) < len(impressoes):
        console.print(f"  [dim]Arte das {len(com_arte)} primeiras; a lista abaixo tem todas.[/]")
    await mostrar_impressoes_em_grade(com_arte)

    escolha = await questionary.select(
        "Qual impressao usar?",
        choices=[
            questionary.Choice(
                f"{c.set_name} · {descrever_impressao(c)}",
                c,
            )
            for c in impressoes
        ],
    ).ask_async()
    if escolha is None:
        raise KeyboardInterrupt
    return escolha
