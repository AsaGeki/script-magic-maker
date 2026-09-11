"""Traducao pt do MTG Arena, via o banco publicado por mtgatool-metadata.

Cobre o buraco do Scryfall: a Wizards parou de IMPRIMIR em portugues depois de
Modern Horizons 3, mas o Arena continua traduzindo carta nova. Pra carta
pos-corte, e a unica fonte oficial de portugues que existe - fonte secundaria,
so consultada quando o Scryfall nao resolve sozinho.

O banco vem de https://github.com/mtgatool/mtgatool-metadata (GPL-3.0). E dado
do jogo, nao codigo: consumir o JSON publicado nao puxa GPL pro projeto.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import ARENA_CACHE_DIR, ARENA_CACHE_MAX_DIAS, SCRYFALL_USER_AGENT

logger = logging.getLogger(__name__)

URL_BANCO = (
    "https://github.com/mtgatool/mtgatool-metadata/releases/latest/download/{idioma}-database.json"
)
TIMEOUT = 60.0

# {oT} = tap, {oC} = incolor, {o1} = generico... o Arena usa o mesmo simbolo
# do Scryfall com um "o" extra na frente.
_SIMBOLO_ARENA = re.compile(r"\{o([^}]*)\}")

_bancos: dict[str, dict] = {}
_indice_pt: dict[tuple[str, str], dict] | None = None
_trava = asyncio.Lock()
# Depois de uma falha, para de tentar pelo resto do processo: senao uma busca
# com dezenas de cartas repete o mesmo timeout de rede uma vez por carta.
_falhou = False


@dataclass
class TraducaoArena:
    """O que da pra aproveitar da carta traduzida no Arena.

    Sem tipo de carta: Types/Subtypes/Supertypes do Arena sao rotulo interno,
    sempre em ingles, nao texto pra mostrar.
    """

    nome: str
    texto: str | None  # None quando alguma linha ainda esta em ingles
    flavor_text: str | None


def _caminho(idioma: str) -> Path:
    return ARENA_CACHE_DIR / f"{idioma}-database.json"


def _desatualizado(caminho: Path) -> bool:
    if not caminho.is_file():
        return True
    idade_dias = (time.time() - caminho.stat().st_mtime) / 86400
    return idade_dias > ARENA_CACHE_MAX_DIAS


async def _garantir_baixado(client: httpx.AsyncClient, idioma: str) -> Path:
    caminho = _caminho(idioma)
    if not _desatualizado(caminho):
        return caminho

    resposta = await client.get(URL_BANCO.format(idioma=idioma), follow_redirects=True)
    resposta.raise_for_status()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(resposta.content)
    return caminho


async def _carregar(idioma: str) -> dict:
    """Le o banco do disco, baixando (ou reaproveitando o cache) se preciso.

    Uma trava so pra nao baixar 2 vezes em paralelo quando varias cartas
    pedem tradução ao mesmo tempo - o cache em memoria depois disso e so
    leitura, sem trava.
    """
    if idioma in _bancos:
        return _bancos[idioma]
    async with _trava:
        if idioma in _bancos:
            return _bancos[idioma]
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": SCRYFALL_USER_AGENT}
        ) as client:
            caminho = await _garantir_baixado(client, idioma)
        _bancos[idioma] = json.loads(caminho.read_text(encoding="utf-8"))
    return _bancos[idioma]


def _construir_indice(banco_pt: dict) -> dict[tuple[str, str], dict]:
    """(set do Scryfall, numero do colecionador) -> carta do Arena.

    O campo `Set` e o codigo interno do Arena; o mapeamento pro do Scryfall
    vive em `sets[nome]['scryfall']`. Carta rebalanceada do Alchemy
    (IsDigitalOnly) fica de fora: nao tem impressao em papel que bata.

    Carta de duas faces vem como duas entradas com o mesmo numero, e quem
    nomeia a impressao e a frente (`IsPrimaryCard`) - sem isso a de tras entra
    por ultimo e a carta sai com o nome do verso na frente.
    """
    codigo_para_scryfall = {
        info["code"]: info["scryfall"]
        for info in banco_pt.get("sets", {}).values()
        if info.get("scryfall")
    }
    indice: dict[tuple[str, str], dict] = {}
    for carta in banco_pt.get("cards", {}).values():
        if carta.get("IsDigitalOnly") or not carta.get("CollectorNumber"):
            continue
        chave = _onde_mora_no_scryfall(carta, codigo_para_scryfall)
        if chave is None:
            continue
        if chave in indice and not carta.get("IsPrimaryCard"):
            continue
        indice[chave] = carta
    return indice


def _onde_mora_no_scryfall(
    carta: dict, codigo_para_scryfall: dict[str, str]
) -> tuple[str, str] | None:
    """Em que (edicao, numero) do Scryfall esta impressao do Arena mora.

    Ficha vai pelo campo `Art`: no Scryfall ela tem edicao propria ("TKHM"),
    mas o Arena guarda com o `Set` da edicao-mae e um numero que colide com o
    de uma carta de verdade. Fora ficha o `Art` nao serve - em milhares de
    cartas ele aponta pra onde o Arena pegou a ilustracao, nao pra impressao.
    """
    if carta.get("IsToken"):
        arte = carta.get("Art") or {}
        if not (arte.get("s") and arte.get("n")):
            return None
        return (str(arte["s"]).lower(), str(arte["n"]))

    set_scryfall = codigo_para_scryfall.get(carta.get("Set", ""))
    if not set_scryfall:
        return None
    return (set_scryfall.lower(), str(carta["CollectorNumber"]))


def _transformar_texto(bruto: str, nome_traduzido: str) -> str:
    """Do jeito que o Arena guarda pro jeito que o Scryfall guarda."""
    texto = _SIMBOLO_ARENA.sub(r"{\1}", bruto)
    return texto.replace("CARDNAME", nome_traduzido)


def _reconstruir_regras(
    carta_pt: dict, banco_pt: dict, banco_en: dict, nome_traduzido: str
) -> str | None:
    """Junta as linhas de AbilityIds, ou None se alguma ainda esta em ingles.

    A traducao do Arena e por linha, nao por carta: e comum uma habilidade vir
    traduzida e a de baixo nao. Aqui e tudo ou nada - uma linha identica ao
    ingles derruba a carta inteira pro "sem regra confiavel".
    """
    linhas = []
    for id_habilidade in carta_pt.get("AbilityIds", []):
        chave = str(id_habilidade)
        linha_pt = banco_pt.get("abilities", {}).get(chave)
        linha_en = banco_en.get("abilities", {}).get(chave)
        if linha_pt is None:
            return None
        if linha_en is not None and linha_pt == linha_en:
            return None
        linhas.append(linha_pt)
    if not linhas:
        return None
    return "\n".join(_transformar_texto(linha, nome_traduzido) for linha in linhas)


async def buscar_traducao(codigo_da_edicao: str, numero: str) -> TraducaoArena | None:
    """A traducao do Arena pra impressao exata, se existir no banco.

    None quando a carta nao esta no Arena, quando a regra nao saiu traduzida
    (ver _reconstruir_regras) ou quando o banco nao pode ser baixado: esta
    fonte nunca trava quem chamou.
    """
    global _indice_pt, _falhou  # noqa: PLW0603 - cache do modulo, ver o topo
    if _falhou:
        return None
    try:
        banco_pt = await _carregar("pt")
        banco_en = await _carregar("en")
    except (httpx.HTTPError, OSError) as erro:
        _falhou = True
        logger.warning("Traducao do Arena desativada nesta execucao: %s", erro)
        return None
    if _indice_pt is None:
        _indice_pt = _construir_indice(banco_pt)

    carta_pt = _indice_pt.get((codigo_da_edicao.lower(), numero))
    if carta_pt is None:
        return None
    carta_en = banco_en.get("cards", {}).get(str(carta_pt["GrpId"]), {})

    nome = carta_pt.get("Name") or ""
    if not nome or nome == carta_en.get("Name"):
        return None  # nome identico ao ingles = nao traduzido de verdade

    flavor = carta_pt.get("FlavorText") or None
    if flavor and flavor == carta_en.get("FlavorText"):
        flavor = None

    texto = _reconstruir_regras(carta_pt, banco_pt, banco_en, nome)
    return TraducaoArena(nome=nome, texto=texto, flavor_text=flavor)
