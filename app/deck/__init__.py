"""Importação de lista de deck e geração em lote."""

from app.deck.geracao import CartaResolvida, ResultadoDoDeck, gerar_deck, resolver
from app.deck.lista import EntradaDeDeck, analisar_lista, cartas_unicas, ler_arquivo

__all__ = [
    "CartaResolvida",
    "EntradaDeDeck",
    "ResultadoDoDeck",
    "analisar_lista",
    "cartas_unicas",
    "gerar_deck",
    "ler_arquivo",
    "resolver",
]
