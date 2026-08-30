"""Orquestra o fluxo de deck: da lista em texto ate as cartas resolvidas no
Scryfall. Sem nenhum questionary aqui - quem pergunta e o menu (app.cli.menu).
"""

import logging

from app.cards.models import ScryfallCard
from app.cards.service import find_card_by_name, find_card_by_print
from app.deck.texto import EntradaDeDeck
from app.errors import AppError

logger = logging.getLogger(__name__)


async def buscar_cartas_do_deck(
    entradas: list[EntradaDeDeck], permitir_ingles: bool = True
) -> tuple[list[ScryfallCard], list[str]]:
    """Traduz cada entrada da lista numa carta do Scryfall.

    Retorna (cartas, avisos). Uma entrada que falha vira aviso e as outras
    seguem - lista de deck com 1 nome errado nao pode derrubar o lote inteiro.
    """
    cartas: list[ScryfallCard] = []
    avisos: list[str] = []

    for entrada in entradas:
        try:
            carta = await _resolver(entrada, permitir_ingles)
        except AppError as erro:
            avisos.append(f"{entrada.nome}: {erro.message}")
            continue
        carta.copias = entrada.quantidade
        cartas.append(carta)

    return cartas, avisos


async def _resolver(entrada: EntradaDeDeck, permitir_ingles: bool) -> ScryfallCard:
    """Impressao exata quando a linha traz edicao e numero; senao, pelo nome."""
    if entrada.set and entrada.collector_number:
        carta = await find_card_by_print(entrada.set, entrada.collector_number)
        if carta is None and permitir_ingles:
            carta = await find_card_by_print(
                entrada.set, entrada.collector_number, lang="en"
            )
        if carta is not None:
            return carta
        logger.info(
            '"%s": impressao %s #%s nao encontrada, caindo na busca por nome',
            entrada.nome,
            entrada.set.upper(),
            entrada.collector_number,
        )

    return await find_card_by_name(entrada.nome, permitir_ingles=permitir_ingles)
