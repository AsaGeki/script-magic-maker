"""Quais palavras saem em itálico no texto de regras.

Em carta impressa, **palavra de habilidade** (Enrage, Landfall) vem em itálico
antes do travessão; **palavra-chave** (Boast, Cycling) vem em redondo. O
Scryfall não separa as duas, mas o MTGJSON publica a divisão oficial em
`Keywords.json` — de lá vêm as duas listas, e não de uma tabela mantida aqui.

`Keywords.json` demora a incorporar coleção nova: FIN saiu com Stagger e Super
Nova em itálico na carta impressa e nenhuma das duas está em `abilityWords`. O
`keywords` da própria impressão, no Scryfall, traz as duas — e é por isso que o
gerador cruza as duas fontes: palavra que a carta lista e que não é
palavra-chave é palavra de habilidade.
"""

import asyncio
import logging

import httpx

from app import rede

logger = logging.getLogger(__name__)

URL_DAS_PALAVRAS = "https://mtgjson.com/api/v5/Keywords.json"
TIMEOUT = 20.0

# Uma entrada por lista, preenchida na primeira carta da execução. Falha entra
# como tupla vazia: com a chave posta, as cartas seguintes não repetem a
# consulta quebrada. Dicionário, e não variável solta, pra escrever sem `global`.
_CACHE: dict[str, tuple[str, ...]] = {}
_PALAVRAS_DE_HABILIDADE = "abilityWords"
_PALAVRAS_CHAVE = "keywordAbilities"
_trava = asyncio.Lock()


async def palavras_de_habilidade() -> tuple[str, ...]:
    """As palavras de habilidade, em inglês, como o MTGJSON as lista.

    Devolve vazio quando a consulta falha - aí o gerador fica com a lista de
    exceções que ele já tem embutida, que cobre o grosso.
    """
    return await _lista(_PALAVRAS_DE_HABILIDADE)


async def palavras_chave() -> tuple[str, ...]:
    """As palavras-chave, em inglês, como o MTGJSON as lista.

    Elas são o avesso: o que está aqui sai em redondo mesmo quando a impressão
    lista como keyword.
    """
    return await _lista(_PALAVRAS_CHAVE)


async def _lista(chave: str) -> tuple[str, ...]:
    if chave in _CACHE:
        return _CACHE[chave]
    async with _trava:
        if chave not in _CACHE:
            _CACHE.update(await _buscar())
    return _CACHE.get(chave, ())


async def _buscar() -> dict[str, tuple[str, ...]]:
    """As duas listas, numa consulta só."""
    vazio = {_PALAVRAS_DE_HABILIDADE: (), _PALAVRAS_CHAVE: ()}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=rede.CABECALHOS_DE_API) as client:
            resposta = await client.get(URL_DAS_PALAVRAS)
        resposta.raise_for_status()
        dados = resposta.json()
    except (httpx.HTTPError, ValueError) as erro:
        logger.info("Nao deu pra buscar as palavras de habilidade no MTGJSON: %s", erro)
        return vazio
    return {chave: tuple(dados.get("data", {}).get(chave, [])) for chave in vazio}
