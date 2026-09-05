"""Fichas (tokens) que as cartas do deck criam.

O Scryfall liga carta e ficha pelo campo `all_parts`, mas so na impressao em
ingles - na em portugues ele vem vazio, entao a descoberta passa sempre pela
inglesa.

Ficha em portugues nao existe no Scryfall: `t:token include:extras lang:pt`
devolve zero, de qualquer edicao. Entao o portugues e montado de duas fontes:

- **nome**: banco do MTG Arena (ver app.cards.arena), que traz "Tesouro";
- **regras**: o lembrete entre parenteses da propria carta que cria a ficha,
  que é texto oficial impresso. So vale quando da pra CONFERIR que a extracao
  acertou - ver `_regra_em_portugues`.

A linha de tipo e montada peca por peca (ver `_linha_de_tipo_em_portugues`),
porque nenhuma fonte tem ela pronta: o Arena guarda tipo como rotulo interno,
sempre em ingles, e o MTGJSON traz ficha com `foreignData` nulo.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.cards.arena import TraducaoArena
from app.cards.models import ScryfallCard
from app.cards.service import _buscar, find_card_by_id
from app.config import SCRYFALL_USER_AGENT

logger = logging.getLogger(__name__)

BASE_SCRYFALL = "https://api.scryfall.com"
TIMEOUT = 30.0
CABECALHOS = {"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"}

# O Scryfall pede ~100ms entre requisicoes, igual app.cards.service.
INTERVALO_ENTRE_REQUISICOES = 0.1

_LEMBRETE = re.compile(r"\(([^()]*)\)")
_ENTRE_ASPAS = re.compile(r"[\"“”]([^\"“”]+)[\"“”]")

# O travessao que separa tipo de subtipo na linha de tipo do Scryfall.
TRAVESSAO = "—"

# "create two Treasure tokens" -> Treasure | "crie duas fichas de Tesouro" ->
# Tesouro. Servem pra pegar o subtipo que so existe em ficha (Tesouro, Comida,
# Pista), que carta nenhuma tem pra consultar.
_SUBTIPO_EN = re.compile(r"\b([A-Z][\w'/-]*(?:\s+[A-Z][\w'/-]*)*)\s+tokens?\b")
_SUBTIPO_PT = re.compile(
    r"\bfichas?\s+de\s+([A-ZÀ-Ú][\wÀ-ÿ'/-]*(?:\s+[A-ZÀ-Ú][\wÀ-ÿ'/-]*)*)"
)

# A palavra "ficha" vem DEPOIS do tipo, como o espanhol faz ("Artefacto ficha
# - Tesoro") e como o proprio portugues ja faz com supertipo ("Criatura
# Lendaria", "Terreno Basico"). Nao ha ficha em portugues em fonte nenhuma pra
# confirmar - o Scryfall tem 0, so 2 em espanhol e 39 em japones sem texto.
MARCA_DE_FICHA = "ficha"


@dataclass
class FichaDoDeck:
    """Uma ficha e quem no deck pede por ela."""

    carta: ScryfallCard
    criada_por: list[str] = field(default_factory=list)


async def descobrir(cartas: list[ScryfallCard]) -> list[FichaDoDeck]:
    """As fichas que este deck implica, uma por ficha distinta.

    Duas cartas que criam Tesouro rendem uma ficha so - o que muda e a lista
    de quem cria, que o menu mostra pra dar contexto na hora de escolher.
    """
    achadas: dict[str, FichaDoDeck] = {}

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=CABECALHOS) as client:
        for carta in cartas:
            for parte in await _partes_de_ficha(client, carta):
                nome = parte.get("name") or ""
                if nome in achadas:
                    achadas[nome].criada_por.append(carta.nome_exibido)
                    continue
                ficha = await _montar_ficha(client, parte, carta)
                if ficha is not None:
                    achadas[nome] = FichaDoDeck(carta=ficha, criada_por=[carta.nome_exibido])

    return list(achadas.values())


async def _partes_de_ficha(client: httpx.AsyncClient, carta: ScryfallCard) -> list[dict]:
    """As entradas de ficha do all_parts, lidas da impressao em ingles."""
    await asyncio.sleep(INTERVALO_ENTRE_REQUISICOES)
    try:
        resposta = await client.get(
            f"{BASE_SCRYFALL}/cards/{carta.set}/{carta.collector_number}/en"
        )
    except httpx.HTTPError as erro:
        logger.info('%s: nao deu pra consultar as fichas (%s)', carta.nome_exibido, erro)
        return []
    if resposta.status_code != 200:
        return []
    partes = resposta.json().get("all_parts") or []
    return [parte for parte in partes if parte.get("component") == "token"]


async def _montar_ficha(
    client: httpx.AsyncClient, parte: dict, criadora: ScryfallCard
) -> ScryfallCard | None:
    """Busca a ficha no Scryfall e enche o que der de portugues."""
    try:
        ficha = await find_card_by_id(parte["id"])
    except Exception as erro:  # noqa: BLE001 - ficha e extra, nunca derruba o deck
        logger.info('Ficha "%s" nao pode ser buscada: %s', parte.get("name"), erro)
        return None

    # printed_type_line e o campo que o resto do app ja le como "linha de tipo
    # no idioma local" (ver tipo_exibido); a ficha nao tem impressao em
    # portugues, entao ele chega vazio e sobra pra linha montada aqui.
    ficha.printed_type_line = await _linha_de_tipo_em_portugues(client, ficha, criadora)

    nome = ficha.arena.nome if ficha.arena else None
    regra = (
        _regra_em_portugues(criadora, ficha)
        or await _regra_de_outra_criadora(client, ficha)
        or await _linha_solta_em_portugues(client, ficha)
    )
    if nome or regra:
        # Reaproveita o caminho que o gerador ja usa pra texto nao impresso
        # (ver preferir_arena em app.maker.service) em vez de abrir outro.
        ficha.arena = TraducaoArena(
            nome=nome or ficha.nome_exibido,
            texto=regra,
            flavor_text=None,
        )
    return ficha


async def _linha_de_tipo_em_portugues(
    client: httpx.AsyncClient, ficha: ScryfallCard, criadora: ScryfallCard
) -> str | None:
    """Monta "Artefato ficha - Tesouro" a partir da linha em ingles.

    Cada metade sai de dado real, nunca de tabela: o tipo ("Artifact",
    "Creature") vem da linha de tipo traduzida de uma carta em portugues que
    tenha o mesmo tipo, e o subtipo idem. Subtipo que so existe em ficha
    (Tesouro, Comida) nao tem carta pra consultar e cai no lembrete da
    carta-mae, do mesmo jeito conferido de `_regra_em_portugues`.

    So o lugar da palavra "ficha" e inferido (ver MARCA_DE_FICHA). Se qualquer
    peca faltar, devolve None e a linha fica inteira em ingles - meia
    traduzida seria pior.
    """
    tipos_en, _, subtipos_en = (ficha.type_line or "").partition(TRAVESSAO)
    tipos_en = re.sub(r"^\s*Token\b", "", tipos_en).strip()
    subtipos_en = subtipos_en.strip()
    if not tipos_en:
        # Ficha generica ("Copy", "Poison") traz a linha de tipo so com
        # "Token": nao sobra tipo pra traduzir, e a linha inteira e a marca.
        return None if subtipos_en else MARCA_DE_FICHA.capitalize()

    tipos_pt = await _metade_traduzida(client, tipos_en, subtipo=False)
    if tipos_pt is None:
        return None
    esquerda = f"{tipos_pt} {MARCA_DE_FICHA}"
    if not subtipos_en:
        return esquerda

    subtipos_pt = await _metade_traduzida(client, subtipos_en, subtipo=True)
    if subtipos_pt is None:
        subtipos_pt = _subtipo_do_lembrete(criadora, subtipos_en)
    if subtipos_pt is None:
        return None
    return f"{esquerda} {TRAVESSAO} {subtipos_pt}"


async def _metade_traduzida(
    client: httpx.AsyncClient, em_ingles: str, *, subtipo: bool
) -> str | None:
    """Como o portugues escreve esta metade da linha de tipo.

    Procura uma impressao em portugues que tenha exatamente a mesma metade em
    ingles e le a metade correspondente do `printed_type_line` dela. Comparar
    a metade inteira, e nao palavra por palavra, evita casar "Artifact" com
    "Artifact Creature".
    """
    consulta = " ".join(f't:"{palavra}"' for palavra in em_ingles.split())
    await asyncio.sleep(INTERVALO_ENTRE_REQUISICOES)
    try:
        resposta = await client.get(
            f"{BASE_SCRYFALL}/cards/search",
            params={"q": f"{consulta} lang:pt", "unique": "cards"},
        )
    except httpx.HTTPError:
        return None
    if resposta.status_code != 200:
        return None

    for bruta in resposta.json().get("data", []):
        traduzida = bruta.get("printed_type_line")
        if not traduzida:
            continue
        metade_en = _metade(bruta.get("type_line", ""), subtipo)
        metade_pt = _metade(traduzida, subtipo)
        if metade_en.lower() == em_ingles.lower() and metade_pt:
            return metade_pt
    return None


def _metade(linha: str, subtipo: bool) -> str:
    tipos, _, subtipos = linha.partition(TRAVESSAO)
    return (subtipos if subtipo else tipos).strip()


def _subtipo_do_lembrete(criadora: ScryfallCard, em_ingles: str) -> str | None:
    """Subtipo que so existe em ficha, tirado do texto da carta que a cria.

    Mesma conferencia de `_regra_em_portugues`: o subtipo lido do texto em
    ingles tem que bater com o subtipo da ficha antes de valer a leitura do
    texto em portugues.
    """
    achado_en = _SUBTIPO_EN.search(criadora.oracle_text or "")
    if not achado_en or achado_en.group(1).strip().lower() != em_ingles.lower():
        return None
    achado_pt = _SUBTIPO_PT.search(criadora.printed_text or "")
    return achado_pt.group(1).strip() if achado_pt else None


def _regra_em_portugues(criadora: ScryfallCard, ficha: ScryfallCard) -> str | None:
    """A regra da ficha em portugues, tirada do lembrete da carta que a cria.

    A carta que cria a ficha descreve ela entre parenteses, com a habilidade
    entre aspas - texto oficial, ja impresso em portugues. Extrair dali so e
    confiavel quando da pra provar que a extracao funciona: a MESMA extracao
    rodada no ingles tem que devolver exatamente o oracle_text da ficha. Se
    nao devolver, o lembrete nao descreve essa ficha desse jeito e o texto
    fica em ingles em vez de sair um chute.
    """
    conferencia = _ability_entre_aspas(criadora.oracle_text)
    alvo = _sem_ponto_final(ficha.oracle_text)
    if not conferencia or not alvo or conferencia.lower() != alvo.lower():
        return None
    return _ability_entre_aspas(criadora.printed_text)


# Quantas cartas consultar procurando o lembrete traduzido antes de desistir.
CANDIDATAS_DE_LEMBRETE = 8

# A linha solta exige varrer mais cartas: a palavra-chave costuma vir
# junto de outras na mesma linha, e so serve quem a tem sozinha.
CANDIDATAS_DE_LINHA_SOLTA = 30


async def _regra_de_outra_criadora(
    client: httpx.AsyncClient, ficha: ScryfallCard
) -> str | None:
    """O lembrete da ficha tirado de outra carta que cria a mesma ficha.

    A carta-mae do deck nem sempre descreve a ficha: o Oko em portugues traz so
    "Crie uma ficha de Comida.", sem o lembrete que o ingles tem. Outras cartas
    que criam a mesma ficha trazem - e a conferencia continua a mesma, a
    extracao no ingles tem que bater com o oracle_text da ficha, entao nenhuma
    candidata entra sem prova.
    """
    alvo = _sem_ponto_final(ficha.oracle_text)
    if not alvo:
        return None
    try:
        candidatas = await _buscar(client, f'oracle:"{ficha.name} token"', "pt", unique="cards")
    except Exception as erro:  # noqa: BLE001 - lembrete e extra, nunca derruba o deck
        logger.info('Ficha "%s": busca de lembrete falhou (%s)', ficha.name, erro)
        return None

    for candidata in candidatas[:CANDIDATAS_DE_LEMBRETE]:
        conferencia = _ability_entre_aspas(candidata.oracle_text)
        if not conferencia or conferencia.lower() != alvo.lower():
            continue
        em_portugues = _ability_entre_aspas(candidata.printed_text)
        if em_portugues:
            return em_portugues
    return None


async def _linha_solta_em_portugues(
    client: httpx.AsyncClient, ficha: ScryfallCard
) -> str | None:
    """Ficha cujo texto e uma linha so, sem lembrete que descreva ela.

    E o caso da palavra-chave sozinha ("Flying"): nao ha carta que a coloque
    entre aspas, entao a extracao por lembrete nao acha nada. Aqui a prova e
    outra, a mesma da isencao de italico: numa carta em portugues, a linha
    equivalente e a que ocupa a MESMA posicao no texto em ingles.
    """
    alvo = (ficha.oracle_text or "").strip()
    if not alvo or len(alvo.splitlines()) != 1:
        return None
    # A busca vai so com o que vem antes do lembrete: a frase inteira entre
    # parenteses e comprida demais e o Scryfall nao acha nada com ela.
    procurado = alvo.split("(")[0].strip().rstrip(".").strip()
    try:
        candidatas = await _buscar(client, f'oracle:"{procurado}"', "pt", unique="cards")
    except Exception as erro:  # noqa: BLE001 - texto da ficha e extra
        logger.info('Ficha "%s": busca de linha solta falhou (%s)', ficha.name, erro)
        return None

    reserva = None
    for candidata in candidatas[:CANDIDATAS_DE_LINHA_SOLTA]:
        em_ingles = (candidata.oracle_text or "").splitlines()
        em_portugues = (candidata.printed_text or "").splitlines()
        if len(em_ingles) != len(em_portugues):
            continue
        for indice, linha in enumerate(em_ingles):
            traduzida = em_portugues[indice].strip()
            if not traduzida or not _mesma_linha(linha, alvo):
                continue
            # A ficha que traz lembrete merece uma linha que tambem traga; a
            # sem lembrete fica guardada caso nao apareca nenhuma completa.
            if "(" in alvo and "(" not in traduzida:
                reserva = reserva or traduzida
                continue
            return traduzida
    return reserva


def _mesma_linha(em_ingles: str, alvo: str) -> bool:
    """Duas linhas dizem a mesma coisa.

    O lembrete entre parenteses e comparado a parte porque a mesma
    palavra-chave sai com redacao um pouco diferente entre a ficha e a carta;
    o que precisa bater exato e o que vem antes dele.
    """
    def sem_lembrete(texto: str) -> str:
        return texto.split("(")[0].strip().rstrip(".").strip().lower()

    return sem_lembrete(em_ingles) == sem_lembrete(alvo) and bool(sem_lembrete(alvo))


def _ability_entre_aspas(texto: str | None) -> str | None:
    """A habilidade entre aspas dentro do primeiro lembrete que tiver uma."""
    for lembrete in _LEMBRETE.findall(texto or ""):
        entre_aspas = _ENTRE_ASPAS.search(lembrete)
        if entre_aspas:
            return _sem_ponto_final(entre_aspas.group(1))
    return None


def _sem_ponto_final(texto: str | None) -> str | None:
    """O ponto final entra ou sai conforme a frase esteja dentro ou fora das
    aspas, e isso varia de carta pra carta - comparar sem ele evita descartar
    uma extracao certa por causa de 1 caractere."""
    if not texto:
        return None
    return texto.strip().rstrip(".").strip()
