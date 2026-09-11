"""Carta pelo banco do MTGJSON, a saida de quando o Scryfall nao responde.

O Scryfall e a fonte primaria, mas limita requisicao por IP: uma lista de deck
inteira leva 429 no meio do caminho e as cartas que faltaram viram aviso. O
MTGJSON publica o mesmo acervo como um SQLite unico (AllPrintings.sqlite,
~650 MB em disco), baixado uma vez e consultado local, sem limite nenhum.

O que muda em relacao ao Scryfall:

- o texto em portugues mora em cardForeignData, uma linha por impressao por
  idioma; o resto da impressao (moldura, raridade, artista, numero) vem de
  cards, que e sempre a versao em ingles;
- carta de mais de uma face vem como uma linha por face, com o mesmo numero de
  colecionador e o campo `side` separando as duas - e dai que sai card_faces;
- a arte continua vindo da rede, mas pelo CDN de imagem do Scryfall, que e
  outro host e nao entra no limite da API. A URL se monta a partir do id do
  Scryfall, que o MTGJSON guarda em cardIdentifiers.
"""

import asyncio
import gzip
import logging
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from app import rede
from app.cards.models import ScryfallCard
from app.config import (
    MTGJSON_CACHE_DIR,
    MTGJSON_CACHE_MAX_DIAS,
)

logger = logging.getLogger(__name__)

URL_BANCO = "https://mtgjson.com/api/v5/AllPrintings.sqlite.gz"
TIMEOUT = 300.0

IDIOMA_PT = "Portuguese (Brazil)"

# O CDN de imagem do Scryfall, indexado pelo id da carta: os dois primeiros
# caracteres viram diretorio.
BASE_IMAGENS = "https://cards.scryfall.io"

# Layout do MTGJSON que o Scryfall chama de outra coisa. O resto passa direto -
# quando o nome nao existe no enum, Layout cai em UNKNOWN sozinho.
LAYOUT_EQUIVALENTE = {"aftermath": "split"}

# Layouts em que a segunda face e o VERSO da carta fisica, e por isso tem arte
# propria no CDN. Nos outros (dividida, aventura, virada) as duas faces dividem
# a mesma imagem.
LAYOUTS_COM_VERSO = frozenset({"transform", "modal_dfc", "reversible_card", "double_faced_token"})

_conexao: sqlite3.Connection | None = None
_trava = asyncio.Lock()
# Depois de uma falha, para de tentar pelo resto do processo: senao um deck
# inteiro repete o mesmo download quebrado uma vez por carta.
_falhou = False

_COLUNAS = """
    c.name, c.faceName, c.side, c.setCode, c.number, c.layout, c.rarity,
    c.manaCost, c.manaValue, c.type, c.text, c.flavorText,
    c.power, c.toughness, c.loyalty, c.hand, c.life,
    c.colors, c.colorIdentity, c.colorIndicator, c.artist,
    c.borderColor, c.frameVersion, c.frameEffects, c.promoTypes, c.finishes,
    c.securityStamp, c.isFullArt, c.isPromo, c.isTextless,
    i.scryfallId, i.scryfallOracleId, i.scryfallIllustrationId,
    s.name as setName, s.releaseDate,
    f.name as ptName, f.faceName as ptFaceName, f.type as ptType,
    f.text as ptText, f.flavorText as ptFlavor
"""

# A juncao com cardForeignData e o que decide o idioma: obrigatoria pra pedir a
# impressao em portugues, opcional pra pedir a em ingles.
_DE = """
    from cards c
    join sets s on s.code = c.setCode
    join cardIdentifiers i on i.uuid = c.uuid
    {juncao} cardForeignData f on f.uuid = c.uuid and f.language = :idioma
    where coalesce(s.isOnlineOnly, 0) = 0
"""

# Mesma ordem que o Scryfall devolve em unique=prints: da impressao mais nova
# pra mais velha.
_ORDEM = " order by s.releaseDate desc, c.setCode, c.number, c.side"


def _caminho_do_banco() -> Path:
    return MTGJSON_CACHE_DIR / "AllPrintings.sqlite"


async def _baixar(caminho: Path) -> None:
    """Baixa o .gz e descompacta no lugar, tudo em arquivo temporario.

    Sao 230 MB compactados que viram 650 MB em disco, entao nada disso passa
    pela memoria e nada vira o banco definitivo antes de terminar - download
    cortado no meio nao pode deixar um SQLite pela metade pra proxima execucao
    achar que esta pronto.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    compactado = caminho.with_suffix(".sqlite.gz.parcial")
    logger.warning("Baixando o banco do MTGJSON (230 MB, so na primeira vez): %s", URL_BANCO)
    async with (
        httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, headers=rede.CABECALHOS_DE_ARQUIVO
        ) as client,
        client.stream("GET", URL_BANCO) as resposta,
    ):
        resposta.raise_for_status()
        with compactado.open("wb") as saida:
            async for pedaco in resposta.aiter_bytes(1024 * 1024):
                saida.write(pedaco)

    await asyncio.to_thread(_descompactar, compactado, caminho)
    compactado.unlink(missing_ok=True)
    logger.warning("Banco do MTGJSON pronto em %s", caminho)


def _descompactar(compactado: Path, destino: Path) -> None:
    parcial = destino.with_suffix(".sqlite.parcial")
    with gzip.open(compactado, "rb") as entrada, parcial.open("wb") as saida:
        shutil.copyfileobj(entrada, saida, 1024 * 1024)
    parcial.replace(destino)


async def _banco() -> sqlite3.Connection | None:
    """A conexao com o banco, baixando na primeira vez que alguem precisa.

    None quando o download falha - esta fonte e a saida de emergencia e nunca
    derruba quem chamou.
    """
    global _conexao, _falhou  # noqa: PLW0603 - cache do modulo, ver o topo
    if _conexao is not None:
        return _conexao
    if _falhou:
        return None
    async with _trava:
        if _conexao is not None:
            return _conexao
        caminho = _caminho_do_banco()
        try:
            if rede.cache_vencido(caminho, MTGJSON_CACHE_MAX_DIAS):
                await _baixar(caminho)
            _conexao = sqlite3.connect(caminho, check_same_thread=False)
            _conexao.row_factory = sqlite3.Row
        except (httpx.HTTPError, OSError, sqlite3.Error) as erro:
            _falhou = True
            logger.warning("Banco do MTGJSON desativado nesta execucao: %s", erro)
            return None
    return _conexao


async def _consultar(condicao: str, parametros: dict[str, Any], lang: str) -> list[sqlite3.Row]:
    banco = await _banco()
    if banco is None:
        return []
    juncao = "join" if lang == "pt" else "left join"
    consulta = f"select {_COLUNAS} {_DE.format(juncao=juncao)} and {condicao} {_ORDEM}"
    parametros = {**parametros, "idioma": IDIOMA_PT}
    return await asyncio.to_thread(lambda: banco.execute(consulta, parametros).fetchall())


# Onde procurar o nome, na ordem: o da carta em ingles (unico indexado), o de
# uma face dela, e por fim os traduzidos. Todas devolvem o nome cheio da carta,
# nunca o de uma face solta - senao a carta de duas faces sairia pela metade.
_ONDE_PROCURAR = (
    "c.name = :nome",
    "c.name in (select name from cards where faceName = :nome)",
    """c.name in (
        select c2.name from cards c2
        join cardForeignData f2 on f2.uuid = c2.uuid and f2.language = :idioma
        where f2.name = :nome or f2.faceName = :nome
    )""",
)


async def disponivel() -> bool:
    """Se da pra consultar o banco - quem chamou usa isso pra separar "esta
    carta nao existe assim" de "nao deu pra procurar"."""
    return await _banco() is not None


async def impressoes_por_nome(nome: str, lang: str) -> list[ScryfallCard]:
    """Todas as impressoes de um nome exato, da mais nova pra mais velha.

    Equivale ao `!"nome" lang:xx` do Scryfall, inclusive em aceitar tanto o
    nome de uma face quanto o nome traduzido.
    """
    for onde in _ONDE_PROCURAR:
        linhas = await _consultar(onde, {"nome": nome}, lang)
        if linhas:
            return _montar_impressoes(linhas, lang)
    return []


async def impressao_exata(codigo_da_edicao: str, numero: str, lang: str) -> ScryfallCard | None:
    """A impressao que a lista de deck pediu pela edicao e pelo numero."""
    linhas = await _consultar(
        "c.setCode = :edicao and c.number = :numero",
        {"edicao": codigo_da_edicao.upper(), "numero": numero},
        lang,
    )
    impressoes = _montar_impressoes(linhas, lang)
    return impressoes[0] if impressoes else None


async def linha_de_tipo_equivalente(em_ingles: str | None) -> str | None:
    """A linha de tipo traduzida de outra carta com a MESMA linha em ingles.

    Mesma ideia da versao que consulta o Scryfall (ver
    app.cards.service._linha_de_tipo_equivalente), so que aqui a igualdade e
    exata: o banco guarda a linha inteira dos dois lados.
    """
    if not em_ingles:
        return None
    banco = await _banco()
    if banco is None:
        return None
    consulta = (
        "select f.type from cards c "
        "join cardForeignData f on f.uuid = c.uuid and f.language = :idioma "
        "where c.type = :tipo and f.type is not null limit 1"
    )
    linha = await asyncio.to_thread(
        lambda: banco.execute(consulta, {"tipo": em_ingles, "idioma": IDIOMA_PT}).fetchone()
    )
    return linha["type"] if linha else None


def _montar_impressoes(linhas: list[sqlite3.Row], lang: str) -> list[ScryfallCard]:
    """Agrupa as linhas por impressao - uma carta de duas faces sao duas
    linhas com a mesma edicao e o mesmo numero."""
    por_impressao: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for linha in linhas:
        por_impressao.setdefault((linha["setCode"], linha["number"]), []).append(linha)
    return [_montar(faces, lang) for faces in por_impressao.values()]


def _montar(linhas: list[sqlite3.Row], lang: str) -> ScryfallCard:
    """Uma impressao do MTGJSON no formato que o Scryfall devolveria.

    Carta de meld fica so na face `a`: e assim que o Scryfall a trata, com o
    resultado do meld como carta separada.
    """
    layout = LAYOUT_EQUIVALENTE.get(linhas[0]["layout"], linhas[0]["layout"])
    frente = linhas[0]
    if len(linhas) > 1 and layout != "meld":
        dados = _varias_faces(linhas, lang, layout)
    else:
        dados = _face(frente, lang)
        dados["image_uris"] = _imagens(frente["scryfallId"], verso=False)
    dados |= {
        "id": frente["scryfallId"],
        "oracle_id": frente["scryfallOracleId"],
        "lang": lang,
        "layout": layout,
        "rarity": frente["rarity"],
        "set": frente["setCode"].lower(),
        "set_name": frente["setName"],
        "collector_number": frente["number"],
        "released_at": frente["releaseDate"],
        "cmc": frente["manaValue"],
        "color_identity": _lista(frente["colorIdentity"]) or [],
        "frame": frente["frameVersion"],
        "border_color": frente["borderColor"],
        "full_art": bool(frente["isFullArt"]),
        "frame_effects": _lista(frente["frameEffects"]),
        "promo": bool(frente["isPromo"]),
        "promo_types": _lista(frente["promoTypes"]),
        "textless": bool(frente["isTextless"]),
        "finishes": _lista(frente["finishes"]),
        "security_stamp": frente["securityStamp"],
        "hand_modifier": frente["hand"],
        "life_modifier": frente["life"],
    }

    return ScryfallCard.model_validate(dados)


def _varias_faces(linhas: list[sqlite3.Row], lang: str, layout: str) -> dict[str, Any]:
    """O topo da carta de mais de uma face, do jeito que o Scryfall monta.

    Nome, linha de tipo e custo aparecem com as duas metades separadas por
    " // ", e nada de texto fica no topo: nome traduzido, regras e historia
    moram dentro das faces. So quem tem verso de verdade (transform e afins)
    tem uma arte por face; na dividida e na aventura a carta e uma imagem so.
    """
    tem_verso = layout in LAYOUTS_COM_VERSO
    faces = []
    for indice, linha in enumerate(linhas):
        face = _face(linha, lang)
        face["image_uris"] = _imagens(linha["scryfallId"], verso=indice > 0) if tem_verso else None
        faces.append(face)

    frente = linhas[0]
    custos = [face["mana_cost"] for face in faces if face["mana_cost"]]
    cores = dict.fromkeys(cor for face in faces for cor in (face["colors"] or []))
    topo = {
        "name": frente["name"],
        "card_faces": faces,
        "type_line": " // ".join(face["type_line"] or "" for face in faces),
        # O ilustrador e' da impressao, nao da face: fica no topo em qualquer
        # layout, e e' por ele que a busca de arte confere a ilustracao. Cada
        # face pode ter o seu, e ai o Scryfall lista os dois juntos.
        "artist": " & ".join(dict.fromkeys(linha["artist"] for linha in linhas if linha["artist"])),
    }
    if tem_verso:
        return topo
    # Uma face fisica so: custo, cor, arte e os numeros da criatura sao os da
    # frente, porque e' a carta inteira.
    return topo | {
        "mana_cost": " // ".join(custos) if custos else None,
        "colors": list(cores),
        "image_uris": _imagens(frente["scryfallId"], verso=False),
        "power": faces[0]["power"],
        "toughness": faces[0]["toughness"],
        "loyalty": faces[0]["loyalty"],
        "flavor_text": faces[0]["flavor_text"],
    }


def _face(linha: sqlite3.Row, lang: str) -> dict[str, Any]:
    """Os campos que carta e face tem em comum (ver models.FaceBase).

    `faceName` so vem preenchido em carta de mais de uma face; na de uma face
    so o nome cheio existe.
    """
    traduzido = lang == "pt"
    return {
        "name": linha["faceName"] or linha["name"],
        "printed_name": (linha["ptFaceName"] or linha["ptName"]) if traduzido else None,
        "mana_cost": linha["manaCost"],
        "type_line": linha["type"],
        "printed_type_line": linha["ptType"] if traduzido else None,
        "oracle_text": _sem_colchete_de_lealdade(linha["text"]),
        "printed_text": linha["ptText"] if traduzido else None,
        # Historia so no idioma da impressao: impressao antiga em portugues
        # costuma nao ter nenhuma, e a inglesa no lugar sairia impressa em
        # ingles numa carta em portugues.
        "flavor_text": linha["ptFlavor"] if traduzido else linha["flavorText"],
        "power": linha["power"],
        "toughness": linha["toughness"],
        "loyalty": linha["loyalty"],
        "colors": _lista(linha["colors"]),
        "color_indicator": _lista(linha["colorIndicator"]),
        "artist": linha["artist"],
        "illustration_id": linha["scryfallIllustrationId"],
    }


# O MTGJSON poe o custo de lealdade do planeswalker entre colchetes ("[+1]:",
# "[-X]:"); a carta impressa e o Scryfall escrevem sem eles. O menos do banco e
# o U+2212, escrito como escape pra nao se confundir com o hifen ao lado.
_COLCHETE_DE_LEALDADE = re.compile(r"^\[([+\u2212-]?(?:\d+|X))\]:", re.MULTILINE)


def _sem_colchete_de_lealdade(texto: str | None) -> str | None:
    if not texto:
        return texto
    return _COLCHETE_DE_LEALDADE.sub(r"\1:", texto)


def _imagens(id_scryfall: str | None, verso: bool) -> dict[str, str] | None:
    """O art_crop no CDN de imagem do Scryfall.

    E' o unico formato que o projeto usa (ver models.FaceBase.art_crop), e vem
    do CDN e nao da API: a URL se monta sozinha a partir do id, e o limite de
    requisicao que derrubou a consulta nao vale aqui.
    """
    if not id_scryfall:
        return None
    lado = "back" if verso else "front"
    caminho = f"{id_scryfall[0]}/{id_scryfall[1]}/{id_scryfall}.jpg"
    return {"art_crop": f"{BASE_IMAGENS}/art_crop/{lado}/{caminho}"}


def _lista(valor: str | None) -> list[str] | None:
    """Campo de varios valores: o SQLite guarda "B, G" onde o Scryfall manda
    ["B", "G"].

    Texto vazio e lista vazia (carta incolor tem `colors` ""), diferente de
    NULL, que e' campo sem valor nenhum.
    """
    if valor is None:
        return None
    return [parte.strip() for parte in valor.split(",") if parte.strip()]
