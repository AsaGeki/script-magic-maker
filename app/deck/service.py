"""Orquestra o fluxo de deck: da lista em texto ate as cartas resolvidas no
Scryfall. Sem nenhum questionary aqui - quem pergunta e o menu (app.cli.menu).
"""

import logging

from app.cards.models import ScryfallCard
from app.cards.service import find_card_by_name, find_card_by_print
from app.deck.texto import EntradaDeDeck
from app.errors import AppError
from app.slug import slug

logger = logging.getLogger(__name__)


async def buscar_cartas_do_deck(
    entradas: list[EntradaDeDeck], permitir_ingles: bool = True
) -> tuple[list[tuple[EntradaDeDeck, ScryfallCard]], list[str]]:
    """Traduz cada entrada da lista numa carta do Scryfall.

    Retorna (pares, avisos), cada par com a entrada que originou a carta - e
    a entrada que diz se a linha travou a impressao ou nao, e quem quiser
    reescrever a linha depois precisa dela. Uma entrada que falha vira aviso e
    as outras seguem: lista de deck com 1 nome errado nao pode derrubar o lote
    inteiro.
    """
    pares: list[tuple[EntradaDeDeck, ScryfallCard]] = []
    avisos: list[str] = []

    for entrada in entradas:
        try:
            carta = await _resolver(entrada, permitir_ingles)
        except AppError as erro:
            avisos.append(f"{entrada.nome}: {erro.message}")
            continue
        carta.copias = entrada.quantidade
        pares.append((entrada, carta))

    return pares, avisos


async def _resolver(entrada: EntradaDeDeck, permitir_ingles: bool) -> ScryfallCard:
    """Impressao exata quando a linha traz edicao e numero; senao, pelo nome.

    A impressao pedida pode nao ter PT (ex.: reimpressao em colecao pos-corte
    de traducao) mesmo quando a carta tem PT em outra edicao. Por isso, antes
    de aceitar ingles, tenta achar a mesma carta por nome em PT - so cai pro
    ingles da impressao exata se nem isso existir.
    """
    if entrada.set and entrada.collector_number:
        carta = await find_card_by_print(entrada.set, entrada.collector_number)
        if carta is not None and _e_a_carta_da_linha(entrada.nome, carta):
            return carta
        if carta is not None:
            logger.warning(
                '"%s": %s #%s e "%s", nao "%s" - seguindo pelo nome',
                entrada.nome,
                entrada.set.upper(),
                entrada.collector_number,
                carta.nome_exibido,
                entrada.nome,
            )
        else:
            logger.info(
                '"%s": impressao %s #%s nao encontrada em PT, procurando a carta '
                "em outra edicao antes de cair pro ingles",
                entrada.nome,
                entrada.set.upper(),
                entrada.collector_number,
            )
            try:
                return await find_card_by_name(entrada.nome, permitir_ingles=False)
            except AppError:
                pass
            if permitir_ingles:
                carta_en = await find_card_by_print(
                    entrada.set, entrada.collector_number, lang="en"
                )
                if carta_en is not None and _e_a_carta_da_linha(entrada.nome, carta_en):
                    return carta_en

    return await find_card_by_name(entrada.nome, permitir_ingles=permitir_ingles)


def _e_a_carta_da_linha(nome_pedido: str, carta: ScryfallCard) -> bool:
    """Se a impressao achada pela edicao e numero e mesmo a carta que a linha
    nomeia.

    Edicao e numero errados apontam pra outra carta sem dar erro nenhum - a
    consulta acha uma impressao valida, so que nao a pedida. Sem conferir o
    nome, o deck sai com a carta trocada em silencio.

    O slug compara sem acento nem maiuscula, e a face da frente entra sozinha
    pra carta de nome composto, onde a linha costuma trazer so a primeira.
    """
    nomes = set()
    for nome in (carta.name, carta.nome_exibido):
        nomes.add(slug(nome))
        nomes.add(slug(nome.split(" // ")[0]))
    return slug(nome_pedido) in nomes
