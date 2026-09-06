"""Quais palavras saem em itálico no texto de regras.

Em carta impressa, **palavra de habilidade** (Enrage, Landfall) vem em itálico
antes do travessão; **palavra-chave** (Boast, Cycling) vem em redondo. O
Scryfall não separa as duas, mas o MTGJSON publica a divisão oficial em
`Keywords.json` — de lá vem a lista, e não de uma tabela mantida aqui.
"""

import json
import logging
import urllib.request
from functools import lru_cache

from app.config import SCRYFALL_USER_AGENT

logger = logging.getLogger(__name__)

URL_DAS_PALAVRAS = "https://mtgjson.com/api/v5/Keywords.json"
TIMEOUT = 20.0


@lru_cache(maxsize=1)
def palavras_de_habilidade() -> tuple[str, ...]:
    """As palavras de habilidade, em inglês, como o MTGJSON as lista.

    Devolve vazio quando a consulta falha - aí o gerador fica com a lista de
    exceções que ele já tem embutida, que cobre o grosso.
    """
    requisicao = urllib.request.Request(
        URL_DAS_PALAVRAS, headers={"User-Agent": SCRYFALL_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT) as resposta:
            dados = json.load(resposta)
    except Exception as erro:  # noqa: BLE001 - sem a lista o gerador ainda funciona
        logger.info("Nao deu pra buscar as palavras de habilidade no MTGJSON: %s", erro)
        return ()
    return tuple(dados.get("data", {}).get("abilityWords", []))
