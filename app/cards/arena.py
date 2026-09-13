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
from dataclasses import dataclass
from pathlib import Path

import httpx

from app import rede
from app.config import ARENA_CACHE_DIR, ARENA_CACHE_MAX_DIAS

logger = logging.getLogger(__name__)

URL_BANCO = (
    "https://github.com/mtgatool/mtgatool-metadata/releases/latest/download/{idioma}-database.json"
)
TIMEOUT = 60.0

# {oT} = tap, {oC} = incolor, {o1} = generico... o Arena usa o mesmo simbolo do
# Scryfall com um "o" extra na frente, e empacota o custo inteiro entre uma
# chave so: "{o1oB}" sao dois simbolos, "{oWoUoBoRoG}" sao cinco.
_SIMBOLO_ARENA = re.compile(r"\{o([^}]*)\}")

_bancos: dict[str, dict] = {}
# Os indices sao montados na primeira busca e guardados aqui dentro: o dict e
# mutado, nunca trocado, entao nenhuma funcao precisa de `global`.
_indices: dict[str, dict[tuple[str, str], dict]] = {}
_trava = asyncio.Lock()
# Depois de uma falha, para de tentar pelo resto do processo: senao uma busca
# com dezenas de cartas repete o mesmo timeout de rede uma vez por carta.
_estado = {"falhou": False}


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


async def _garantir_baixado(client: httpx.AsyncClient, idioma: str) -> Path:
    caminho = _caminho(idioma)
    if not rede.cache_vencido(caminho, ARENA_CACHE_MAX_DIAS):
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
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=rede.CABECALHOS_DE_ARQUIVO) as client:
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


def _abrir_simbolos(achado: re.Match[str]) -> str:
    """Um par de chaves por simbolo, e o hibrido sem os parenteses do Arena:
    "{o1oB}" vira "{1}{B}" e "{o(B/G)}" vira "{B/G}"."""
    return "".join(
        f"{{{simbolo.strip('()')}}}" for simbolo in achado.group(1).split("o") if simbolo
    )


def _transformar_texto(bruto: str, nome_traduzido: str) -> str:
    """Do jeito que o Arena guarda pro jeito que o Scryfall guarda."""
    texto = _SIMBOLO_ARENA.sub(_abrir_simbolos, bruto)
    return texto.replace("CARDNAME", nome_traduzido)


def _habilidades(
    carta_pt: dict,
    banco_pt: dict,
    banco_en: dict,
    nome_traduzido: str,
    nome_em_ingles: str,
) -> list[tuple[str | None, str]] | None:
    """(ingles, portugues) de cada habilidade, ou None se alguma nao traduziu.

    A traducao do Arena e por linha, nao por carta: e comum uma habilidade vir
    traduzida e a de baixo nao. Aqui e tudo ou nada - uma linha identica ao
    ingles derruba a carta inteira pro "sem regra confiavel".
    """
    pares: list[tuple[str | None, str]] = []
    for id_habilidade in carta_pt.get("AbilityIds", []):
        chave = str(id_habilidade)
        linha_pt = banco_pt.get("abilities", {}).get(chave)
        linha_en = banco_en.get("abilities", {}).get(chave)
        if linha_pt is None:
            return None
        if linha_en is not None and linha_pt == linha_en:
            return None
        pares.append(
            (
                _transformar_texto(linha_en, nome_em_ingles) if linha_en else None,
                _transformar_texto(linha_pt, nome_traduzido),
            )
        )
    return pares or None


def _minuscula_inicial(texto: str) -> str:
    return texto[:1].lower() + texto[1:]


def _traduzir_linha(linha: str, por_ingles: dict[str, str]) -> str | None:
    """A linha do ingles em portugues, ou None se alguma parte nao tem par.

    Tenta a linha inteira primeiro; so quebra nas virgulas se ela nao existir
    como habilidade - assim "Exile target creature, then draw a card." nao vira
    duas buscas. A caixa da inicial segue a do ingles: numa linha de
    palavras-chave so a primeira comeca em maiuscula.
    """
    inteira = por_ingles.get(linha.casefold())
    if inteira is not None:
        return inteira
    partes = []
    for pedaco in linha.split(", "):
        traduzido = por_ingles.get(pedaco.casefold())
        if traduzido is None:
            return None
        partes.append(traduzido if pedaco[:1].isupper() else _minuscula_inicial(traduzido))
    return ", ".join(partes)


def _nas_linhas_do_ingles(
    texto_em_ingles: str | None, habilidades: list[tuple[str | None, str]]
) -> str | None:
    """O portugues com a quebra de linha da carta em ingles, ou None.

    O Arena guarda uma habilidade por linha e a carta impressa junta as
    palavras-chave com virgula: sem isso o Eldrazi de sete palavras-chave sai em
    sete linhas, e a carta impressa tem quatro.
    """
    if not texto_em_ingles:
        return None
    por_ingles = {ingles.casefold(): pt for ingles, pt in habilidades if ingles}
    if not por_ingles:
        return None
    linhas = []
    for linha in texto_em_ingles.split("\n"):
        traduzida = _traduzir_linha(linha, por_ingles)
        if traduzida is None:
            return None
        linhas.append(traduzida)
    return "\n".join(linhas)


def _construir_indice_de_ficha(
    banco_en: dict, indice: dict[tuple[str, str], dict]
) -> dict[tuple[str, str], dict]:
    """(edicao de ficha, nome em ingles) -> ficha do Arena.

    A mesma ficha sai em varios numeros do Scryfall, um por ilustracao, e o
    Arena guarda so o da arte dele: "Eldrazi Spawn" e TMH3 2 la e TMH3 38 aqui.
    Dentro de uma edicao de ficha o nome em ingles identifica a ficha - a arte
    muda, a regra nao.
    """
    por_nome: dict[tuple[str, str], dict] = {}
    for (edicao, _), carta_pt in indice.items():
        if not carta_pt.get("IsToken"):
            continue
        nome_en = banco_en.get("cards", {}).get(str(carta_pt.get("GrpId")), {}).get("Name")
        if nome_en:
            por_nome.setdefault((edicao, nome_en.casefold()), carta_pt)
    return por_nome


async def buscar_traducao(
    codigo_da_edicao: str,
    numero: str,
    texto_em_ingles: str | None = None,
    nome_em_ingles: str | None = None,
) -> TraducaoArena | None:
    """A traducao do Arena pra impressao exata, se existir no banco.

    `texto_em_ingles` e o oracle_text da carta: e dele que sai a quebra de
    linha (ver _nas_linhas_do_ingles). Sem ele vale a do Arena, uma habilidade
    por linha.

    `nome_em_ingles` so entra em ficha, quando o numero nao bate (ver
    _construir_indice_de_ficha).

    None quando a carta nao esta no Arena, quando a regra nao saiu traduzida
    (ver _habilidades) ou quando o banco nao pode ser baixado: esta fonte nunca
    trava quem chamou.
    """
    if _estado["falhou"]:
        return None
    try:
        banco_pt = await _carregar("pt")
        banco_en = await _carregar("en")
    except (httpx.HTTPError, OSError) as erro:
        _estado["falhou"] = True
        logger.warning("Traducao do Arena desativada nesta execucao: %s", erro)
        return None
    if "impressao" not in _indices:
        _indices["impressao"] = _construir_indice(banco_pt)
        _indices["ficha"] = _construir_indice_de_ficha(banco_en, _indices["impressao"])

    edicao = codigo_da_edicao.lower()
    carta_pt = _indices["impressao"].get((edicao, numero))
    if carta_pt is None and nome_em_ingles:
        carta_pt = _indices["ficha"].get((edicao, nome_em_ingles.casefold()))
    if carta_pt is None:
        return None
    carta_en = banco_en.get("cards", {}).get(str(carta_pt["GrpId"]), {})

    nome = carta_pt.get("Name") or ""
    if not nome:
        return None

    habilidades = _habilidades(carta_pt, banco_pt, banco_en, nome, carta_en.get("Name") or "")
    # Nome de personagem nao muda de idioma - "Tifa Lockhart" e "Vivi Ornitier"
    # saem iguais nos dois. Nome igual so prova que a entrada nao tem portugues
    # nenhum quando a regra tambem nao tem.
    if nome == carta_en.get("Name") and habilidades is None:
        return None

    flavor = carta_pt.get("FlavorText") or None
    if flavor and flavor == carta_en.get("FlavorText"):
        flavor = None

    texto = None
    if habilidades is not None:
        texto = _nas_linhas_do_ingles(texto_em_ingles, habilidades) or "\n".join(
            pt for _, pt in habilidades
        )
    return TraducaoArena(nome=nome, texto=texto, flavor_text=flavor)
