"""Menu interativo.

Sem argumento, o `cli.py` cai aqui: escolhe a carta, mostra o que veio do
Scryfall e só então gera a imagem. O navegador é aberto na primeira geração e
reaproveitado nas seguintes.
"""

from pathlib import Path

import questionary
from rich.console import Console

from app.cards.models import ScryfallCard
from app.cards.scryfall import ScryfallClient
from app.cli.preview import mostrar_carta
from app.deck import cartas_unicas, gerar_deck, ler_arquivo, resolver
from app.errors import ErroDoApp
from app.maker.browser import MOLDURAS, MOLDURA_PADRAO
from app.maker.conjurer import Conjurer

console = Console()

SAIR = "Sair"
LIMITE_SUGESTOES = 15


def menu() -> None:
    """Laço principal do menu."""
    conjurer: Conjurer | None = None
    try:
        with ScryfallClient() as cliente:
            while True:
                escolha = questionary.select(
                    "O que vamos fazer?",
                    choices=["Gerar uma carta", "Gerar um deck", SAIR],
                ).ask()

                if escolha is None or escolha == SAIR:
                    return
                if escolha == "Gerar um deck":
                    conjurer = _rodar_deck(cliente, conjurer)
                    continue

                carta = escolher_carta(cliente)
                if carta is None:
                    continue

                mostrar_carta(carta, console)
                moldura = confirmar_geracao()
                if moldura is None:
                    continue

                if conjurer is None:
                    console.print("[dim]Abrindo o Card Conjurer…[/dim]")
                    conjurer = Conjurer(moldura=moldura).start()
                else:
                    conjurer.moldura = moldura

                try:
                    caminho = conjurer.gerar(carta)
                except ErroDoApp as erro:
                    console.print(f"[red]{erro}[/red]")
                    continue
                console.print(f"[green]{caminho}[/green]")
    finally:
        if conjurer is not None:
            conjurer.stop()


def _rodar_deck(cliente: ScryfallClient, conjurer: Conjurer | None) -> Conjurer | None:
    """Lê a lista, resolve as cartas e gera todas. Devolve o navegador em uso."""
    caminho = questionary.text("Arquivo da lista (.txt ou .dec):").ask()
    if not caminho:
        return conjurer

    try:
        entradas = cartas_unicas(ler_arquivo(Path(caminho.strip().strip('"'))))
    except ErroDoApp as erro:
        console.print(f"[red]{erro}[/red]")
        return conjurer

    console.print(f"{len(entradas)} cartas distintas.")
    resolvidas, falhas = resolver(entradas, cliente, permitir_ingles=True)
    for nome, motivo in falhas:
        console.print(f"[yellow]{nome}: {motivo}[/yellow]")
    if not resolvidas:
        return conjurer

    if questionary.select(
        f"Gerar {len(resolvidas)} imagens?", choices=["Gerar", "Cancelar"]
    ).ask() != "Gerar":
        return conjurer

    if conjurer is None:
        console.print("[dim]Abrindo o Card Conjurer…[/dim]")
        conjurer = Conjurer().start()

    resultado = gerar_deck(
        resolvidas,
        conjurer,
        ao_iniciar=lambda i, total, carta: console.print(
            f"[dim]{i}/{total}[/dim] {carta.nome_exibido}"
        ),
    )
    console.print(f"[green]{len(resultado.geradas)} imagens geradas.[/green]")
    if resultado.em_ingles:
        console.print(f"[yellow]Em inglês: {', '.join(resultado.em_ingles)}[/yellow]")
    for nome, motivo in resultado.falhas:
        console.print(f"[red]{nome}: {motivo}[/red]")
    return conjurer


def escolher_carta(cliente: ScryfallClient) -> ScryfallCard | None:
    """Do que o usuário digitou até uma impressão específica."""
    procurado = questionary.text("Nome da carta (em português ou inglês):").ask()
    if not procurado:
        return None

    nome = _resolver_nome(cliente, procurado.strip())
    if nome is None:
        return None

    impressoes = cliente.buscar(nome, lang="pt")
    if not impressoes:
        impressoes = _sem_portugues(cliente, nome)
        if not impressoes:
            return None

    return _escolher_impressao(impressoes)


def _resolver_nome(cliente: ScryfallClient, procurado: str) -> str | None:
    """Resolve o que foi digitado num nome de carta.

    Tenta o nome exato antes de sugerir: quem digita "Ilha" quer Ilha, não a
    lista de 96 cartas que têm "ilha" no nome.
    """
    for idioma in ("pt", "en"):
        exatas = cliente.buscar(procurado, lang=idioma, unique="cards")
        if exatas:
            return exatas[0].name

    sugestoes = cliente.sugerir_em_portugues(procurado, limite=LIMITE_SUGESTOES)
    if not sugestoes:
        sugestoes = cliente.sugerir(procurado)[:LIMITE_SUGESTOES]
    if not sugestoes:
        console.print(f"[yellow]Nada encontrado para {procurado!r}.[/yellow]")
        return None

    escolha = questionary.select("Qual delas?", choices=[*sugestoes, SAIR]).ask()
    return None if escolha in (None, SAIR) else escolha


def _sem_portugues(cliente: ScryfallClient, nome: str) -> list[ScryfallCard]:
    """A carta não saiu em português: pergunta se gera em inglês ou pula."""
    em_ingles = cliente.buscar(nome, lang="en")
    if not em_ingles:
        console.print(f"[yellow]{nome} não foi encontrada no Scryfall.[/yellow]")
        return []

    console.print(f"[yellow]{nome} não tem impressão em português.[/yellow]")
    resposta = questionary.select(
        "E aí?",
        choices=["Gerar em inglês mesmo assim", "Pular esta carta"],
    ).ask()
    return em_ingles if resposta == "Gerar em inglês mesmo assim" else []


def _escolher_impressao(impressoes: list[ScryfallCard]) -> ScryfallCard | None:
    """Uma impressão só passa direto; várias viram lista de edições."""
    if len(impressoes) == 1:
        return impressoes[0]

    rotulos = {
        f"{c.set_name} ({c.set.upper()}) #{c.collector_number} — {c.artist or 'sem artista'}": c
        for c in impressoes
    }
    escolha = questionary.select("Qual impressão?", choices=[*rotulos, SAIR]).ask()
    return None if escolha in (None, SAIR) else rotulos[escolha]


def confirmar_geracao() -> str | None:
    """Confirma a geração e devolve a moldura escolhida."""
    resposta = questionary.select(
        "Gerar a imagem?",
        choices=["Gerar", "Escolher outra moldura", "Cancelar"],
    ).ask()

    if resposta == "Gerar":
        return MOLDURA_PADRAO
    if resposta != "Escolher outra moldura":
        return None

    escolha = questionary.select("Qual moldura?", choices=[*MOLDURAS, SAIR]).ask()
    return None if escolha in (None, SAIR) else MOLDURAS[escolha]
