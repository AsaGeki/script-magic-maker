"""Quais palavras saem em itálico no texto de regras.

Em carta impressa, **palavra de habilidade** (Enrage, Landfall) vem em itálico
antes do travessão; **palavra-chave** (Boast, Cycling) vem em redondo. O
Scryfall não separa as duas, mas o MTGJSON publica a divisão oficial em
`Keywords.json` — de lá vem a lista, e não de uma tabela mantida aqui.
"""

import asyncio
import logging

import httpx

from app import rede

logger = logging.getLogger(__name__)

URL_DAS_PALAVRAS = "https://mtgjson.com/api/v5/Keywords.json"
TIMEOUT = 20.0

# Uma entrada só, preenchida na primeira carta da execução. Falha entra como
# tupla vazia: com a chave posta, as cartas seguintes não repetem a consulta
# quebrada. Dicionário, e não variável solta, pra escrever sem `global`.
_CACHE: dict[str, tuple[str, ...]] = {}
_CHAVE = "abilityWords"
_trava = asyncio.Lock()


async def palavras_de_habilidade() -> tuple[str, ...]:
    """As palavras de habilidade, em inglês, como o MTGJSON as lista.

    Devolve vazio quando a consulta falha - aí o gerador fica com a lista de
    exceções que ele já tem embutida, que cobre o grosso.
    """
    if _CHAVE in _CACHE:
        return _CACHE[_CHAVE]
    async with _trava:
        if _CHAVE not in _CACHE:
            _CACHE[_CHAVE] = await _buscar()
    return _CACHE[_CHAVE]


async def _buscar() -> tuple[str, ...]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=rede.CABECALHOS_DE_API) as client:
            resposta = await client.get(URL_DAS_PALAVRAS)
        resposta.raise_for_status()
        dados = resposta.json()
    except (httpx.HTTPError, ValueError) as erro:
        logger.info("Nao deu pra buscar as palavras de habilidade no MTGJSON: %s", erro)
        return ()
    return tuple(dados.get("data", {}).get(_CHAVE, []))
