"""Decks pre-construidos oficiais (Commander, Planeswalker, Challenger...) via
MTGJSON - o equivalente Magic ao Structure Deck do script-yugioh-maker (ver
list_structure_decks/find_cards_by_cardset la).

Nao e API oficial da Wizards (o MTGJSON e comunitario), mas cobre o mesmo
papel: indice de todo produto pre-construido, cada 1 com a lista exata de
carta+edicao+numero, o que da pra jogar direto no mesmo pipeline de
app.deck.service (EntradaDeDeck) usado pra importar lista de arquivo.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import (
    ESTRUTURAIS_CACHE_DIR,
    ESTRUTURAIS_CACHE_MAX_DIAS,
    SCRYFALL_USER_AGENT,
)
from app.deck.texto import COMMANDER, MAIN, SIDEBOARD, EntradaDeDeck
from app.errors import UpstreamError

logger = logging.getLogger(__name__)

BASE_URL = "https://mtgjson.com/api/v5"
TIMEOUT = 30.0

# O indice completo do MTGJSON tem 1300+ decks, boa parte relíquia de edição
# antiga (Theme Deck/Sample Deck da 9E, 10E...) que ninguém procura hoje - só
# os tipos modernos de produto pre-construido entram na lista.
TIPOS_RELEVANTES = frozenset(
    {
        "Commander Deck",
        "Planeswalker Deck",
        "Challenger Deck",
        "Duel Deck",
        "Event Deck",
        "Brawl Deck",
    }
)


@dataclass
class DeckEstrutural:
    """1 linha do indice - o suficiente pra listar no menu; a lista de carta
    so vem quando alguem escolhe este e buscar_entradas_do_deck() e chamado."""

    nome: str
    tipo: str
    arquivo: str  # fileName do MTGJSON, usado pra baixar decks/<arquivo>.json
    released_at: str


_indice: list[DeckEstrutural] | None = None
_trava = asyncio.Lock()
_falhou = False


def _caminho_cache(nome_arquivo: str) -> Path:
    return ESTRUTURAIS_CACHE_DIR / nome_arquivo


def _desatualizado(caminho: Path) -> bool:
    if not caminho.is_file():
        return True
    idade_dias = (time.time() - caminho.stat().st_mtime) / 86400
    return idade_dias > ESTRUTURAIS_CACHE_MAX_DIAS


async def _buscar_json(
    client: httpx.AsyncClient, caminho_relativo: str, nome_arquivo_cache: str
) -> dict:
    """Le do cache em disco, baixando (ou reaproveitando) se preciso - mesmo
    esquema do cache do Arena (ver app.cards.arena)."""
    caminho = _caminho_cache(nome_arquivo_cache)
    if _desatualizado(caminho):
        resposta = await client.get(f"{BASE_URL}/{caminho_relativo}")
        resposta.raise_for_status()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(resposta.content)
    return json.loads(caminho.read_text(encoding="utf-8"))


async def _carregar_indice() -> list[DeckEstrutural]:
    """Baixa (ou reaproveita) o DeckList.json 1 vez por processo - trava so
    pra nao disparar 2 downloads em paralelo se o menu for chamado 2x rapido."""
    global _indice, _falhou
    if _indice is not None:
        return _indice
    if _falhou:
        return []
    async with _trava:
        if _indice is not None:
            return _indice
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, headers={"User-Agent": SCRYFALL_USER_AGENT}
            ) as client:
                bruto = await _buscar_json(client, "DeckList.json", "DeckList.json")
        except (httpx.HTTPError, OSError) as erro:
            _falhou = True
            logger.warning("Lista de decks estruturais desativada nesta execucao: %s", erro)
            return []
        _indice = [
            DeckEstrutural(
                nome=item["name"],
                tipo=item["type"],
                arquivo=item["fileName"],
                released_at=item.get("releaseDate", ""),
            )
            for item in bruto.get("data", [])
            if item.get("type") in TIPOS_RELEVANTES
        ]
    return _indice


async def list_tipos_estruturais() -> list[str]:
    """Tipos com pelo menos 1 deck disponivel no indice."""
    indice = await _carregar_indice()
    return sorted({d.tipo for d in indice})


async def list_decks_estruturais(tipo: str) -> list[DeckEstrutural]:
    """Decks de 1 tipo, do mais recente pro mais antigo."""
    indice = await _carregar_indice()
    return sorted(
        (d for d in indice if d.tipo == tipo), key=lambda d: d.released_at, reverse=True
    )


async def buscar_entradas_do_deck(arquivo: str) -> list[EntradaDeDeck]:
    """Baixa 1 deck e converte pro mesmo formato que a importacao de arquivo
    usa - dai pra frente e o pipeline de sempre
    (app.deck.service.buscar_cartas_do_deck), que ja sabe resolver por
    edicao+numero com fallback pro nome."""
    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": SCRYFALL_USER_AGENT}
    ) as client:
        bruto = await _buscar_json(client, f"decks/{arquivo}.json", f"deck-{arquivo}.json")
    deck = bruto.get("data", {})

    entradas = [
        EntradaDeDeck(
            quantidade=carta.get("count", 1),
            nome=carta["name"],
            set=(carta.get("setCode") or "").lower() or None,
            collector_number=carta.get("number"),
            secao=secao,
        )
        for campo, secao in (("commander", COMMANDER), ("mainBoard", MAIN), ("sideBoard", SIDEBOARD))
        for carta in deck.get(campo, [])
    ]
    if not entradas:
        raise UpstreamError(f'O deck "{arquivo}" nao trouxe nenhuma carta')
    return entradas
