"""Em que formatos sancionados o deck poderia entrar, e o que o impede.

A legalidade carta a carta vem do campo `legalities` do Scryfall, consultado em
lote por `/cards/collection` (ate 75 identificadores por chamada). Um formato so
libera o deck quando nenhuma carta esta fora dele E as regras de construcao do
formato batem - tamanho, limite de copias e, no Commander, deck singleton com
comandante.
"""

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from app.cards.models import ScryfallCard
from app.config import SCRYFALL_USER_AGENT

logger = logging.getLogger(__name__)

BASE_URL = "https://api.scryfall.com"
TIMEOUT = 30.0
CABECALHOS = {"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"}

# O Scryfall pede ~100ms entre requisicoes, igual app.cards.service.
INTERVALO_ENTRE_REQUISICOES = 0.1

# Teto de identificadores por chamada em /cards/collection, definido pela API.
IDENTIFICADORES_POR_CHAMADA = 75

MAX_TENTATIVAS_429 = 3
ESPERA_MAXIMA_429 = 2.0

# Os formatos de papel, entre os 23 que o Scryfall devolve em `legalities`.
FORMATOS = ("standard", "pioneer", "modern", "legacy", "vintage", "pauper", "commander")

NOME_DO_FORMATO = {
    "standard": "Standard",
    "pioneer": "Pioneer",
    "modern": "Modern",
    "legacy": "Legacy",
    "vintage": "Vintage",
    "pauper": "Pauper",
    "commander": "Commander",
}

MINIMO_CONSTRUIDO = 60
TAMANHO_COMMANDER = 100
MAXIMO_DE_COPIAS = 4

# Estados de legalities tratados a parte; qualquer outro diferente de LEGAL
# (banned, not_legal) tira a carta do formato.
LEGAL = "legal"
RESTRITA = "restricted"


@dataclass
class CartaTravada:
    """Uma carta e os formatos em que ela nao entra."""

    nome: str
    formatos: list[str] = field(default_factory=list)


@dataclass
class Veredito:
    """O resultado de um formato: entra ou nao, e o que pesa contra."""

    formato: str
    pode_entrar: bool
    impedimentos: list[str] = field(default_factory=list)

    @property
    def rotulo(self) -> str:
        return NOME_DO_FORMATO.get(self.formato, self.formato)


@dataclass
class AnaliseDoDeck:
    """A leitura completa do deck: quanto tem, onde entra e o que trava."""

    total_de_cartas: int
    vereditos: list[Veredito] = field(default_factory=list)
    travadas: list[CartaTravada] = field(default_factory=list)
    # Cartas cuja legalidade o Scryfall nao devolveu. Enquanto for maior que 0,
    # nenhum formato pode ser dado como liberado.
    sem_consulta: int = 0

    @property
    def formatos_liberados(self) -> list[Veredito]:
        return [v for v in self.vereditos if v.pode_entrar]


async def consultar_legalidades(cartas: list[ScryfallCard]) -> dict[str, dict[str, str]]:
    """Legalidade por id de carta. Id que a API nao devolver fica de fora do
    dicionario, e `analisar` trata como carta sem informacao."""
    ids = list({carta.id for carta in cartas})
    legalidades: dict[str, dict[str, str]] = {}

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT, headers=CABECALHOS) as cliente:
        for inicio in range(0, len(ids), IDENTIFICADORES_POR_CHAMADA):
            lote = ids[inicio : inicio + IDENTIFICADORES_POR_CHAMADA]
            corpo = {"identifiers": [{"id": identificador} for identificador in lote]}
            resposta = await _postar_com_retentativa(cliente, corpo)
            if resposta is None:
                continue
            for bruta in resposta.json().get("data", []):
                if bruta.get("id") and bruta.get("legalities"):
                    legalidades[bruta["id"]] = bruta["legalities"]

    return legalidades


async def _postar_com_retentativa(
    cliente: httpx.AsyncClient, corpo: dict
) -> httpx.Response | None:
    """POST em /cards/collection reespera no 429. Devolve None quando desiste -
    quem chama trata as cartas do lote como nao consultadas."""
    for tentativa in range(MAX_TENTATIVAS_429):
        await asyncio.sleep(INTERVALO_ENTRE_REQUISICOES)
        try:
            resposta = await cliente.post("/cards/collection", json=corpo)
        except httpx.HTTPError as erro:
            logger.warning("legalidade indisponivel: %s", erro)
            return None
        if resposta.status_code == 200:
            return resposta
        if resposta.status_code != 429:
            logger.warning("legalidade indisponivel: Scryfall respondeu %s", resposta.status_code)
            return None
        espera = min(float(resposta.headers.get("Retry-After", 1 + tentativa)), ESPERA_MAXIMA_429)
        await asyncio.sleep(espera)
    logger.warning("legalidade indisponivel: Scryfall segue limitando as requisicoes")
    return None


def _copias_por_nome(cartas: list[ScryfallCard]) -> dict[str, int]:
    """Total de copias por nome, ignorando terreno basico - o unico sem teto."""
    total: dict[str, int] = {}
    for carta in cartas:
        if "Basic Land" in (carta.type_line or ""):
            continue
        total[carta.name] = total.get(carta.name, 0) + carta.copias
    return total


def _tem_comandante(cartas: list[ScryfallCard]) -> bool:
    return any("Legendary Creature" in (carta.type_line or "") for carta in cartas)


def analisar(
    cartas: list[ScryfallCard], legalidades: dict[str, dict[str, str]]
) -> AnaliseDoDeck:
    """Cruza a legalidade de cada carta com as regras de construcao de cada
    formato. Carta que a consulta nao alcancou vira impedimento em todos eles,
    pra nenhum formato sair como liberado sem o dado que sustenta isso."""
    total = sum(carta.copias for carta in cartas)
    sem_consulta = sum(1 for carta in cartas if carta.id not in legalidades)
    copias = _copias_por_nome(cartas)
    excedidas = sorted(nome for nome, quantidade in copias.items() if quantidade > MAXIMO_DE_COPIAS)
    repetidas = sorted(nome for nome, quantidade in copias.items() if quantidade > 1)

    travadas_por_nome: dict[str, CartaTravada] = {}
    vereditos: list[Veredito] = []

    for formato in FORMATOS:
        fora: list[str] = []
        for carta in cartas:
            estado = legalidades.get(carta.id, {}).get(formato)
            if estado is None or estado == LEGAL:
                continue
            if estado == RESTRITA and carta.copias <= 1:
                continue
            nome = carta.nome_exibido
            if nome not in fora:
                fora.append(nome)
            travada = travadas_por_nome.setdefault(nome, CartaTravada(nome=nome))
            if formato not in travada.formatos:
                travada.formatos.append(formato)

        impedimentos: list[str] = []
        if sem_consulta:
            impedimentos.append(f"legalidade de {sem_consulta} carta(s) nao consultada")
        if fora:
            impedimentos.append(f"{len(fora)} carta(s) fora do formato")

        if formato == "commander":
            if total != TAMANHO_COMMANDER:
                impedimentos.append(f"deck tem {total} cartas, exige {TAMANHO_COMMANDER} exatas")
            if repetidas:
                impedimentos.append(f"{len(repetidas)} carta(s) repetida(s), exige singleton")
            if not _tem_comandante(cartas):
                impedimentos.append("nenhuma criatura lendaria para ser o comandante")
        else:
            if total < MINIMO_CONSTRUIDO:
                impedimentos.append(f"deck tem {total} cartas, minimo {MINIMO_CONSTRUIDO}")
            if excedidas:
                impedimentos.append(
                    f"{len(excedidas)} carta(s) passando de {MAXIMO_DE_COPIAS} copias"
                )

        vereditos.append(
            Veredito(formato=formato, pode_entrar=not impedimentos, impedimentos=impedimentos)
        )

    travadas = sorted(travadas_por_nome.values(), key=lambda t: t.nome)
    return AnaliseDoDeck(
        total_de_cartas=total,
        vereditos=vereditos,
        travadas=travadas,
        sem_consulta=sem_consulta,
    )


def _e_do_deck(carta: ScryfallCard) -> bool:
    """Ficha e emblema acompanham o deck impresso mas nao sao carta dele: nao
    contam no tamanho, no limite de copias nem na lista de cartas travadas."""
    tipo = (carta.type_line or "").strip().lower()
    return not tipo.startswith(("token", "emblem"))


async def analisar_deck(cartas: list[ScryfallCard]) -> AnaliseDoDeck:
    """Atalho: consulta a legalidade das cartas e ja devolve a analise."""
    do_deck = [carta for carta in cartas if _e_do_deck(carta)]
    return analisar(do_deck, await consultar_legalidades(do_deck))
