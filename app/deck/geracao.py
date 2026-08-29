"""Resolução e geração de um deck inteiro.

Cada entrada da lista vira uma carta do Scryfall e depois uma imagem. Uma carta
que falha não derruba as outras: o resultado diz o que saiu e o que não saiu.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.cards.models import ScryfallCard
from app.cards.scryfall import ScryfallClient
from app.deck.lista import EntradaDeDeck
from app.errors import ErroDoApp
from app.maker.conjurer import Conjurer


@dataclass
class CartaResolvida:
    entrada: EntradaDeDeck
    carta: ScryfallCard


@dataclass
class ResultadoDoDeck:
    """O que saiu, o que ficou em inglês e o que não deu."""

    geradas: list[Path] = field(default_factory=list)
    em_ingles: list[str] = field(default_factory=list)
    falhas: list[tuple[str, str]] = field(default_factory=list)
    # Quantas cópias de cada imagem o deck pede, pra folha de impressão.
    copias: list[tuple[Path, int]] = field(default_factory=list)


def resolver(
    entradas: list[EntradaDeDeck],
    cliente: ScryfallClient,
    permitir_ingles: bool = True,
) -> tuple[list[CartaResolvida], list[tuple[str, str]]]:
    """Traduz cada entrada da lista numa carta do Scryfall.

    Quando a linha traz edição e número, busca aquela impressão; senão, resolve
    pelo nome. Devolve o que resolveu e as falhas, uma mensagem por carta.
    """
    resolvidas: list[CartaResolvida] = []
    falhas: list[tuple[str, str]] = []

    for entrada in entradas:
        try:
            carta = _resolver_uma(entrada, cliente, permitir_ingles)
        except ErroDoApp as erro:
            falhas.append((entrada.nome, str(erro)))
            continue
        if carta is None:
            falhas.append((entrada.nome, "Carta não encontrada."))
            continue
        resolvidas.append(CartaResolvida(entrada=entrada, carta=carta))

    return resolvidas, falhas


def _resolver_uma(
    entrada: EntradaDeDeck, cliente: ScryfallClient, permitir_ingles: bool
) -> ScryfallCard | None:
    if entrada.set and entrada.collector_number:
        carta = cliente.buscar_por_impressao(entrada.set, entrada.collector_number)
        if carta is None and permitir_ingles:
            carta = cliente.buscar_por_impressao(
                entrada.set, entrada.collector_number, lang="en"
            )
        if carta is not None:
            return carta
        # A impressão pedida não existe; o nome ainda pode resolver noutra edição.

    return cliente.buscar_carta(entrada.nome, permitir_ingles=permitir_ingles)


def gerar_deck(
    resolvidas: list[CartaResolvida],
    conjurer: Conjurer,
    ao_iniciar: Callable[[int, int, ScryfallCard], None] | None = None,
) -> ResultadoDoDeck:
    """Gera a imagem de cada carta reaproveitando o mesmo navegador."""
    resultado = ResultadoDoDeck()
    total = len(resolvidas)

    for indice, item in enumerate(resolvidas, start=1):
        if ao_iniciar is not None:
            ao_iniciar(indice, total, item.carta)
        try:
            caminho = conjurer.gerar(item.carta)
        except ErroDoApp as erro:
            resultado.falhas.append((item.carta.nome_exibido, str(erro)))
            continue
        resultado.geradas.append(caminho)
        resultado.copias.append((caminho, item.entrada.quantidade))
        if not item.carta.tem_portugues:
            resultado.em_ingles.append(item.carta.nome_exibido)

    return resultado
