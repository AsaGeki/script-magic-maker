"""Busca de carta no Scryfall - fonte oficial dos dados, sem chave nem
cadastro (so pede User-Agent identificavel e ~100ms entre requisicoes).

Tudo async: o CLI roda dentro de 1 `asyncio.run()` so (ver app.cli.menu) e o
Playwright do app.maker tambem e async, entao nao ha versao sincrona.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.cards import arena
from app.cards.models import ScryfallCard
from app.config import SCRYFALL_USER_AGENT
from app.errors import NotFoundError, UpstreamError

BASE_URL = "https://api.scryfall.com"

# A Wizards parou de imprimir Magic em portugues depois de Modern Horizons 3.
# Edicao lancada depois disso so existe em ingles - ver docs/PESQUISA.md.
ULTIMA_EDICAO_EM_PORTUGUES = "2024-06-14"

# Tipos de colecao que nao rendem carta pra imprimir.
TIPOS_DE_EDICAO_IGNORADOS = frozenset(
    {"token", "memorabilia", "minigame", "vanguard", "planar", "treasure_chest"}
)

# O Scryfall pede ~100ms entre requisicoes; respeitado antes de cada chamada.
INTERVALO_ENTRE_REQUISICOES = 0.1
TIMEOUT = 30.0

# Quantas edicoes checar em paralelo em list_sets - concorrencia modesta,
# ainda bem abaixo do limite de 10 req/s do Scryfall mesmo em rajada.
TAMANHO_DO_LOTE = 5

logger = logging.getLogger(__name__)

CABECALHOS = {"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"}


def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT, headers=CABECALHOS)


MAX_TENTATIVAS_429 = 3
ESPERA_MAXIMA_429 = 2.0


async def _get(
    client: httpx.AsyncClient, caminho: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    for tentativa in range(MAX_TENTATIVAS_429):
        await asyncio.sleep(INTERVALO_ENTRE_REQUISICOES)
        try:
            resposta = await client.get(caminho, params=params)
        except httpx.HTTPError as erro:
            raise UpstreamError(f"Falha ao consultar o Scryfall: {erro}") from erro
        if resposta.status_code != 429:
            return resposta
        # Respeita o Retry-After quando vem, mas com teto: o Scryfall as vezes
        # manda um valor de dezenas de segundos, e nenhuma consulta daqui
        # justifica ficar parado tanto tempo numa unica tentativa (foi o que
        # fez list_sets() parecer travado no menu - poucas consultas com
        # Retry-After alto bastavam pra render minutos no total).
        espera = min(float(resposta.headers.get("Retry-After", 1 + tentativa)), ESPERA_MAXIMA_429)
        await asyncio.sleep(espera)
    return resposta


async def _buscar(
    client: httpx.AsyncClient,
    consulta: str,
    lang: str,
    unique: str = "prints",
) -> list[ScryfallCard]:
    """/cards/search cru. 404 ali significa "nenhum resultado", nao falha."""
    resposta = await _get(
        client, "/cards/search", {"q": f"{consulta} lang:{lang}", "unique": unique}
    )
    if resposta.status_code == 404:
        return []
    if resposta.status_code != 200:
        raise UpstreamError(f"O Scryfall respondeu {resposta.status_code}.")
    cartas = [ScryfallCard.model_validate(item) for item in resposta.json().get("data", [])]
    await _enriquecer_com_arena(cartas)
    return cartas


async def _enriquecer_com_arena(cartas: list[ScryfallCard]) -> None:
    """Anexa a traducao do Arena quando existir - sempre tentado, pra dar pra
    comparar contra o que o Scryfall trouxe (impresso oficial x atual do
    jogo, que podem divergir por errata). So-o-melhor-esforco: falha de rede
    ou banco ja e tratada dentro de app.cards.arena, nunca derruba a busca.
    """
    for carta in cartas:
        carta.arena = await arena.buscar_traducao(carta.set, carta.collector_number)


async def search_cards(nome: str, lang: str = "pt") -> list[ScryfallCard]:
    """Todas as impressoes de um nome exato, no idioma pedido."""
    async with _cliente() as client:
        return await _buscar(client, f'!"{nome}"', lang)


async def search_cards_by_term(termo: str, limite: int = 30) -> list[ScryfallCard]:
    """Busca livre: o termo aparece em qualquer lugar do nome.

    unique="cards" pra nao repetir a mesma carta uma vez por impressao - quem
    escolhe impressao e o passo seguinte.
    """
    async with _cliente() as client:
        achadas = await _buscar(client, termo, "pt", unique="cards")
        if not achadas:
            achadas = await _buscar(client, termo, "en", unique="cards")
        return achadas[:limite]


async def find_card_by_name(nome: str, permitir_ingles: bool = False) -> ScryfallCard:
    """A carta em portugues, com o ingles como saida opcional.

    Levanta ConflictError quando so existe em ingles e permitir_ingles e
    falso, pra que o CLI possa perguntar o que fazer.
    """
    async with _cliente() as client:
        impressoes = await _buscar(client, f'!"{nome}"', "pt")
        if impressoes:
            return impressoes[0]

        em_ingles = await _buscar(client, f'!"{nome}"', "en")
        if not em_ingles:
            raise NotFoundError(f'Carta "{nome}" nao encontrada no Scryfall')
        if not permitir_ingles:
            from app.errors import ConflictError

            raise ConflictError(f'"{nome}" nao tem impressao em portugues')
        logger.warning('"%s": sem impressao em portugues, usando o texto em ingles', nome)
        return em_ingles[0]


async def find_card_by_print(
    codigo_da_edicao: str, numero: str, lang: str = "pt"
) -> ScryfallCard | None:
    """A impressao exata, quando a lista de deck diz a edicao e o numero."""
    async with _cliente() as client:
        resposta = await _get(client, f"/cards/{codigo_da_edicao.lower()}/{numero}/{lang}")
        if resposta.status_code == 404:
            return None
        if resposta.status_code != 200:
            raise UpstreamError(
                f"O Scryfall respondeu {resposta.status_code} para "
                f"{codigo_da_edicao.upper()} #{numero}."
            )
        carta = ScryfallCard.model_validate(resposta.json())
        await _enriquecer_com_arena([carta])
        return carta


async def find_card_by_id(card_id: str) -> ScryfallCard:
    async with _cliente() as client:
        resposta = await _get(client, f"/cards/{card_id}")
        if resposta.status_code == 404:
            raise NotFoundError(f'Impressao "{card_id}" nao encontrada')
        if resposta.status_code != 200:
            raise UpstreamError(f"O Scryfall respondeu {resposta.status_code}.")
        carta = ScryfallCard.model_validate(resposta.json())
        await _enriquecer_com_arena([carta])
        return carta


async def suggest_names(trecho: str, limite: int = 15) -> list[str]:
    """Nomes que completam o trecho digitado, em portugues.

    O /cards/autocomplete do Scryfall so conhece nome em ingles - buscar
    "Raio" ali devolve "Samurai of the Pale Curtain", porque casa a sequencia
    de letras no nome em ingles. Por isso a sugestao em portugues sai da busca
    normal, e o autocomplete oficial fica como reserva.
    """
    async with _cliente() as client:
        achadas = await _buscar(client, trecho, "pt", unique="cards")
        if achadas:
            return [c.nome_exibido for c in achadas[:limite]]

        resposta = await _get(client, "/cards/autocomplete", {"q": trecho})
        if resposta.status_code != 200:
            return []
        return resposta.json().get("data", [])[:limite]


async def _tem_impressao_pt(client: httpx.AsyncClient, codigo_da_edicao: str) -> bool:
    """Se a edicao tem ao menos 1 carta em portugues.

    So le `total_cards` da resposta crua, sem validar os modelos - aqui
    interessa so existir ou nao, nao o conteudo. Falha (429 persistente, erro
    de rede) conta como "nao verificado" - so essa edicao fica de fora da
    lista, sem derrubar list_sets() inteiro por causa de 1 consulta.
    """
    try:
        resposta = await _get(
            client, "/cards/search", {"q": f"set:{codigo_da_edicao} lang:pt", "unique": "cards"}
        )
    except UpstreamError:
        return False
    if resposta.status_code != 200:
        return False
    return resposta.json().get("total_cards", 0) > 0


async def list_sets(limite: int = 60, so_com_portugues: bool = True) -> list[dict]:
    """Edicoes pro fluxo de gerar carta escolhendo a colecao.

    Fora da lista: colecao digital (Arena), de token e afins, que nao rendem
    carta pra imprimir. Com `so_com_portugues`, tambem ficam de fora as
    edicoes sem NENHUMA carta em portugues - verificado de verdade, uma a uma
    (a data do corte de traducao da Wizards so filtra o grosso antes de
    gastar requisicao; promo e coleco especial anterior ao corte tambem podem
    nao ter portugues nenhum, ver docs internos do projeto).

    O `/sets` vem do mais recente pro mais antigo, entao a verificacao para
    assim que junta `limite` edicoes validas. A data do corte ainda entra como
    primeiro filtro, so pra nao gastar uma requisicao por edicao checando as
    dezenas lancadas depois dele - essas sempre falham a verificacao real
    mesmo assim, entao pular direto poupa tempo sem mudar o resultado.

    A verificacao roda em lotes concorrentes (ver TAMANHO_DO_LOTE), nao 1 por
    1 - sequencial demorava minutos numa lista grande e o menu ficava sem
    nenhum retorno na tela, parecendo travado.
    """
    async with _cliente() as client:
        resposta = await _get(client, "/sets")
        if resposta.status_code != 200:
            raise UpstreamError(f"O Scryfall respondeu {resposta.status_code}.")

        candidatas = []
        for s in resposta.json().get("data", []):
            if not s.get("card_count") or s.get("digital"):
                continue
            if s.get("set_type") in TIPOS_DE_EDICAO_IGNORADOS:
                continue
            if so_com_portugues and s.get("released_at", "") > ULTIMA_EDICAO_EM_PORTUGUES:
                continue
            candidatas.append(s)

        edicoes = []
        if not so_com_portugues:
            for s in candidatas[:limite]:
                edicoes.append(_edicao_para_dict(s))
            return edicoes

        for inicio in range(0, len(candidatas), TAMANHO_DO_LOTE):
            if len(edicoes) >= limite:
                break
            lote = candidatas[inicio : inicio + TAMANHO_DO_LOTE]
            resultados = await asyncio.gather(
                *(_tem_impressao_pt(client, s["code"]) for s in lote)
            )
            for s, tem_pt in zip(lote, resultados):
                if tem_pt:
                    edicoes.append(_edicao_para_dict(s))
        return edicoes[:limite]


def _edicao_para_dict(s: dict) -> dict:
    return {
        "code": s["code"],
        "name": s["name"],
        "released_at": s.get("released_at", ""),
        "card_count": s["card_count"],
    }


async def find_cards_by_set(
    codigo_da_edicao: str, limite: int = 60, lang: str = "pt"
) -> list[ScryfallCard]:
    """Cartas de uma edicao no idioma pedido."""
    async with _cliente() as client:
        achadas = await _buscar(client, f"set:{codigo_da_edicao}", lang, unique="cards")
        return achadas[:limite]
