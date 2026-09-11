"""O que todo modulo que fala com servico de fora repete.

Cabecalho, teto de espera, ritmo entre requisicoes e a conta do 429 eram
escritos de novo em cada modulo que consulta o Scryfall, o MTGJSON ou o
MTGPics. Aqui ficam uma vez so, pra que ajustar o ritmo seja mexer num lugar.

A politica de erro NAO mora aqui: cada chamador decide se a falha vira
excecao (app.cards.service) ou log com degradacao (app.deck.legalidade).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import SCRYFALL_USER_AGENT

# O Scryfall pede User-Agent identificavel em vez de chave de API.
CABECALHOS_DE_API = {"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"}

# Pra imagem e pagina HTML, onde pedir JSON so confundiria o servidor.
CABECALHOS_DE_ARQUIVO = {"User-Agent": SCRYFALL_USER_AGENT}

# O Scryfall pede ~100ms entre requisicoes; respeitado antes de cada chamada.
INTERVALO_ENTRE_REQUISICOES = 0.1

TIMEOUT_PADRAO = 30.0

MAX_TENTATIVAS_429 = 3
# Teto da espera: o Scryfall as vezes manda dezenas de segundos no Retry-After,
# e nenhuma consulta do projeto justifica esperar tanto.
ESPERA_MAXIMA_429 = 2.0

SEGUNDOS_POR_DIA = 86400


@dataclass
class _Ritmo:
    """Quando a ultima requisicao saiu, pra espacar a proxima."""

    ultima: float = 0.0


_ritmo = _Ritmo()
_trava_do_ritmo = asyncio.Lock()


async def respeitar_ritmo() -> None:
    """Segura a chamada ate passar o intervalo minimo desde a ultima requisicao.

    Um `sleep` dentro de cada chamada nao limita nada quando ha concorrencia:
    num `asyncio.gather`, todas dormem ao mesmo tempo e disparam juntas. A
    trava serializa so a decisao de quando soltar - a requisicao em si segue
    em paralelo com as outras.
    """
    async with _trava_do_ritmo:
        relogio = asyncio.get_running_loop().time
        espera = _ritmo.ultima + INTERVALO_ENTRE_REQUISICOES - relogio()
        if espera > 0:
            await asyncio.sleep(espera)
        _ritmo.ultima = relogio()


def _espera_do_429(resposta: httpx.Response, tentativa: int) -> float:
    return min(float(resposta.headers.get("Retry-After", 1 + tentativa)), ESPERA_MAXIMA_429)


async def com_retentativa_no_429(
    requisicao: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    """Repete a requisicao enquanto vier 429, respeitando o ritmo entre elas.

    Devolve a ultima resposta - inclusive um 429 teimoso, pra quem chamou
    decidir o que fazer com ele. Erro de rede sobe: so o chamador sabe se isso
    derruba a operacao ou vira degradacao.
    """
    for tentativa in range(MAX_TENTATIVAS_429):
        await respeitar_ritmo()
        resposta = await requisicao()
        if resposta.status_code != httpx.codes.TOO_MANY_REQUESTS:
            return resposta
        if tentativa < MAX_TENTATIVAS_429 - 1:
            await asyncio.sleep(_espera_do_429(resposta, tentativa))
    return resposta


def cache_vencido(caminho: Path, max_dias: float) -> bool:
    """Se o arquivo baixado precisa ser buscado de novo.

    Arquivo que nao existe conta como vencido, que e o caso da primeira vez.
    """
    if not caminho.is_file():
        return True
    idade_dias = (time.time() - caminho.stat().st_mtime) / SEGUNDOS_POR_DIA
    return idade_dias > max_dias
