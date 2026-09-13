"""Busca de carta no Scryfall - sem chave, so User-Agent identificavel e
~100ms entre requisicoes. Tudo async, como o resto do projeto.
"""

import asyncio
import logging
import re
from datetime import date
from typing import Any

import httpx

from app import rede
from app.cards import arena, mtgjson
from app.cards.models import ScryfallCard
from app.errors import ConflictError, NotFoundError, UpstreamError

BASE_URL = "https://api.scryfall.com"

# A Wizards parou de imprimir em portugues depois de Modern Horizons 3.
ULTIMA_EDICAO_EM_PORTUGUES = "2024-06-14"

# Tipos de colecao que nao rendem carta pra imprimir.
TIPOS_DE_EDICAO_IGNORADOS = frozenset(
    {"token", "memorabilia", "minigame", "vanguard", "planar", "treasure_chest"}
)


# Edicoes checadas em paralelo em list_sets, bem abaixo do limite de 10 req/s.
TAMANHO_DO_LOTE = 5

logger = logging.getLogger(__name__)


def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL, timeout=rede.TIMEOUT_PADRAO, headers=rede.CABECALHOS_DE_API
    )


async def _get(
    client: httpx.AsyncClient, caminho: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    """GET no Scryfall. Falha de rede vira UpstreamError; 429 teimoso volta como
    resposta, pro chamador tratar pelo status."""
    try:
        return await rede.com_retentativa_no_429(lambda: client.get(caminho, params=params))
    except httpx.HTTPError as erro:
        raise UpstreamError(f"Falha ao consultar o Scryfall: {erro}") from erro


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
    if resposta.status_code == httpx.codes.NOT_FOUND:
        return []
    if resposta.status_code != httpx.codes.OK:
        raise UpstreamError(f"O Scryfall respondeu {resposta.status_code}.")
    cartas = [ScryfallCard.model_validate(item) for item in resposta.json().get("data", [])]
    await _enriquecer_com_arena(cartas)
    return cartas


async def _impressoes_por_nome(
    client: httpx.AsyncClient, nome: str, lang: str, unique: str = "prints"
) -> list[ScryfallCard]:
    """As impressoes de um nome exato, do Scryfall ou do MTGJSON.

    O MTGJSON so entra quando o Scryfall nao responde - 429 por limite de
    requisicao, que uma lista de deck estoura facil, ou falha de rede. E o
    mesmo acervo em disco, na mesma ordem (ver app.cards.mtgjson).

    Lista vazia continua querendo dizer "nao ha impressao nesse idioma", e nao
    "nao deu pra procurar": sem o banco pra responder, o erro do Scryfall
    segue em frente.
    """
    try:
        return await _buscar(client, f'!"{nome}"', lang, unique=unique)
    except UpstreamError as erro:
        if not await mtgjson.disponivel():
            raise
        logger.warning('"%s": %s Seguindo pelo MTGJSON.', nome, erro.message)
        impressoes = await mtgjson.impressoes_por_nome(nome, lang)
        await _enriquecer_com_arena(impressoes)
        return impressoes


async def _enriquecer_com_arena(cartas: list[ScryfallCard]) -> None:
    """Anexa a traducao do Arena quando existir.

    Sempre tentado, pra dar pra comparar com o que o Scryfall trouxe. Falha de
    rede ou banco e tratada dentro de app.cards.arena e nunca derruba a busca.
    """
    for carta in cartas:
        carta.arena = await arena.buscar_traducao(carta.set, carta.collector_number)


async def search_cards(nome: str, lang: str = "pt") -> list[ScryfallCard]:
    """Todas as impressoes de um nome exato, no idioma pedido.

    Passa pelo _impressoes_por_nome, e nao pelo _buscar cru, pra ter a mesma
    saida pelo MTGJSON que o find_card_by_name: uma lista de deck grande leva
    429 no meio, e sem isso o fluxo do menu morria com o banco local pronto
    em disco.
    """
    async with _cliente() as client:
        return await _impressoes_por_nome(client, nome, lang)


async def search_cards_by_term(termo: str, limite: int = 30) -> list[ScryfallCard]:
    """Busca livre: o termo aparece em qualquer lugar do nome.

    unique="cards" pra nao repetir a carta uma vez por impressao.
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
        impressoes = await _impressoes_por_nome(client, nome, "pt")
        if impressoes:
            return impressoes[0]

        em_ingles = await _impressoes_por_nome(client, nome, "en")
        if not em_ingles:
            raise NotFoundError(f'Carta "{nome}" nao encontrada no Scryfall')
        if not permitir_ingles:
            raise ConflictError(f'"{nome}" nao tem impressao em portugues')
        logger.warning('"%s": sem impressao em portugues, usando o texto em ingles', nome)
        return em_ingles[0]


async def find_card_by_print(
    codigo_da_edicao: str, numero: str, lang: str = "pt"
) -> ScryfallCard | None:
    """A impressao exata, quando a lista de deck diz a edicao e o numero.

    None tanto quando a impressao nao existe naquele idioma quanto quando ela
    nao esta no MTGJSON depois de o Scryfall falhar: quem chamou trata os dois
    do mesmo jeito, procurando a carta por outro caminho.
    """
    async with _cliente() as client:
        try:
            resposta = await _get(client, f"/cards/{codigo_da_edicao.lower()}/{numero}/{lang}")
            if resposta.status_code == httpx.codes.NOT_FOUND:
                return None
            if resposta.status_code != httpx.codes.OK:
                raise UpstreamError(  # noqa: TRY301 - o except abaixo e o desvio pro MTGJSON
                    f"O Scryfall respondeu {resposta.status_code}."
                )
        except UpstreamError as erro:
            if not await mtgjson.disponivel():
                raise
            logger.warning(
                "%s #%s: %s Seguindo pelo MTGJSON.",
                codigo_da_edicao.upper(),
                numero,
                erro.message,
            )
            carta = await mtgjson.impressao_exata(codigo_da_edicao, numero, lang)
        else:
            carta = ScryfallCard.model_validate(resposta.json())
        if carta is None:
            return None
        await _enriquecer_com_arena([carta])
        return carta


# Campos de aparencia que a impressao em portugues as vezes deixa em branco.
# `full_art` fica de fora: o vazio dele e False, indistinguivel de um False de
# verdade.
CAMPOS_DE_MOLDURA = ("frame_effects", "border_color", "frame")


async def completar_moldura_do_ingles(carta: ScryfallCard) -> None:
    """Preenche pela impressao em ingles os campos de aparencia que vierem
    vazios na impressao em portugues.

    O Scryfall trata as duas como cartas separadas e nem sempre repete a
    aparencia na traduzida - ONE #287 traz frame_effects em ingles e nulo em
    portugues. E a mesma carta fisica, entao o dado da inglesa vale.
    """
    if carta.lang == "en":
        return
    faltando = [campo for campo in CAMPOS_DE_MOLDURA if getattr(carta, campo) in (None, [])]
    if not faltando:
        return
    async with _cliente() as client:
        resposta = await _get(client, f"/cards/{carta.set}/{carta.collector_number}/en")
    if resposta.status_code != httpx.codes.OK:
        return
    em_ingles = resposta.json()
    for campo in faltando:
        valor = em_ingles.get(campo)
        if valor not in (None, []):
            setattr(carta, campo, valor)


def preferir_traducao_do_arena(carta: ScryfallCard) -> bool:
    """Se vale trocar o texto impresso pelo do MTG Arena nesta carta.

    So quando nao ha portugues NENHUM: nem nesta impressao, nem emprestado de
    uma irma em papel por completar_traducao_pos_corte. Nome e regra contam
    separado porque ficha costuma ter so um dos dois.
    """
    if carta.traduzida or carta.printed_name:
        return False
    return bool(carta.arena and (carta.arena.nome or carta.arena.texto))


async def completar_traducao_parcial(carta: ScryfallCard) -> None:
    """Preenche pelas irmas em portugues os campos traduzidos que o Scryfall
    deixou vazios NESTA impressao.

    Acontece em colecao especial e promo: SPG #48 traz o nome traduzido e a
    linha de tipo nula. So vale pra impressao que ja e em portugues, senao a
    carta sai meio traduzida. Texto de regras fica de fora: pode ter mudado por
    errata entre uma impressao e outra.

    A linha de tipo ainda tem um ultimo recurso, que vale tambem pra carta que
    so tem o portugues do Arena: ver `_linha_de_tipo_equivalente`.
    """
    if carta.traduzida:
        faltando = [
            campo for campo in ("printed_name", "printed_type_line") if not getattr(carta, campo)
        ]
        if faltando:
            async with _cliente() as client:
                irmas = await _impressoes_por_nome(client, carta.name, "pt")
            for irma in irmas:
                for campo in list(faltando):
                    if valor := getattr(irma, campo):
                        setattr(carta, campo, valor)
                        faltando.remove(campo)
                if not faltando:
                    break

    if carta.printed_type_line or not (carta.traduzida or carta.printed_name):
        return
    async with _cliente() as client:
        carta.printed_type_line = await _linha_de_tipo_equivalente(client, carta.type_line)


async def _linha_de_tipo_equivalente(
    client: httpx.AsyncClient, em_ingles: str | None
) -> str | None:
    """A linha de tipo traduzida de outra carta com a MESMA linha em ingles.

    Diferente de nome e texto, a linha de tipo nao e escrita carta a carta: e
    montada dos mesmos tipos e subtipos, entao a mesma em ingles e a mesma em
    portugues. Cobre a impressao antiga que o Scryfall deixou sem
    printed_type_line (MIR #4) e a carta pos-corte, que so tem o portugues do
    Arena e nem impressao em portugues tem (FDN #47).
    """
    if not em_ingles:
        return None
    palavras = re.findall(r"[\w'-]+", em_ingles)
    if not palavras:
        return None
    consulta = " ".join(f't:"{palavra}"' for palavra in palavras)
    try:
        candidatas = await _buscar(client, consulta, "pt", unique="cards")
    except UpstreamError:
        return await mtgjson.linha_de_tipo_equivalente(em_ingles)
    for candidata in candidatas:
        if candidata.type_line == em_ingles and candidata.printed_type_line:
            return candidata.printed_type_line
    return None


def e_terreno_basico(carta: ScryfallCard) -> bool:
    return (carta.type_line or "").lower().startswith("basic land")


async def traduzir_terreno_basico(carta: ScryfallCard) -> None:
    """Poe o nome em portugues num terreno basico que so existe em ingles.

    Nome fixo e sem texto de regras: o nome traduzido de qualquer impressao
    vale pra esta. Nao serve pra carta com texto, que pode ter errata. Altera
    no lugar e nao faz nada quando ja ha nome traduzido.
    """
    if carta.printed_name or carta.traduzida or not e_terreno_basico(carta):
        return
    async with _cliente() as client:
        impressoes = await _impressoes_por_nome(client, carta.name, "pt", unique="cards")
    if not impressoes or not impressoes[0].printed_name:
        return
    carta.printed_name = impressoes[0].printed_name
    carta.printed_type_line = impressoes[0].printed_type_line


async def completar_traducao_pos_corte(carta: ScryfallCard) -> None:
    """Poe nome, linha de tipo, regras e historia em portugues numa impressao
    sem PT nenhum (pos-corte de traducao).

    Prefere a irma em papel mais recente: e assim que a carta saiu impressa em
    portugues, com os lembretes entre parenteses e as palavras-chave agrupadas
    na mesma linha. O MTG Arena entra so quando nao ha irma nenhuma - ele
    acompanha a errata atual, mas traduz linha a linha, o que troca a ordem dos
    paragrafos e come lembrete. So a arte e o resto dos metadados (edicao,
    numero, artista) ficam da impressao pedida - o rodape mostra eles tal como
    sao, em ingles, pra dar pra saber ao certo qual impressao esta por tras.
    Terreno basico fica de fora, que ja tem o proprio caminho mais simples
    (traduzir_terreno_basico), sem regra nenhuma pra herdar.
    """
    if carta.lang != "en" or carta.printed_name or e_terreno_basico(carta):
        return

    # As irmas em portugues servem ao nome, ao texto e a historia: uma consulta
    # so, reaproveitada pelos tres.
    async with _cliente() as client:
        irmas = await _impressoes_por_nome(client, carta.name, "pt")

        com_traducao = [irma for irma in irmas if irma.printed_name]
        if com_traducao:
            # Nome e texto saem da MESMA irma: o texto de regras repete o nome
            # da carta, e misturar duas impressoes deixa os dois discordando.
            mais_recente = max(com_traducao, key=lambda irma: irma.released_at or date.min)
            carta.printed_name = mais_recente.printed_name
            carta.printed_text = mais_recente.printed_text

        if carta.arena and (not carta.printed_name or not carta.printed_text):
            carta.printed_name = carta.printed_name or carta.arena.nome
            carta.printed_text = carta.printed_text or carta.arena.texto

        if not carta.printed_name:
            return
        if not carta.printed_type_line:
            carta.printed_type_line = await _linha_de_tipo_equivalente(client, carta.type_line)
        if carta.flavor_text:
            equivalente = await _flavor_equivalente(client, carta, irmas)
            do_arena = carta.arena.flavor_text if carta.arena else None
            carta.flavor_text = equivalente or do_arena or carta.flavor_text

    # Cada campo vem de uma consulta propria, e uma que nao respondeu deixa so
    # aquele campo em ingles - o resto da carta sai traduzido do mesmo jeito.
    faltando = [
        nome
        for nome, valor in (
            ("a linha de tipo", carta.printed_type_line),
            ("o texto de regras", carta.printed_text),
        )
        if not valor
    ]
    if faltando:
        logger.warning(
            '"%s": traducao incompleta - %s %s em ingles',
            carta.printed_name,
            " e ".join(faltando),
            "ficam" if len(faltando) > 1 else "fica",
        )


async def _flavor_equivalente(
    client: httpx.AsyncClient, carta: ScryfallCard, em_portugues: list[ScryfallCard]
) -> str | None:
    """A historia em portugues da irma que conta a MESMA historia em ingles.

    Historia e escrita por impressao, nao por carta: cada reimpressao pode
    trazer outra. Por isso a irma so serve quando o ingles dela bate com o
    desta impressao - e o ingles vem da impressao irma em ingles, ja que na
    irma em portugues o campo ja veio traduzido. Sem irma que bata, devolve
    None e o chamador fica com o ingles.
    """
    candidatas = [irma for irma in em_portugues if irma.flavor_text]
    if not candidatas:
        return None
    em_ingles = await _impressoes_por_nome(client, carta.name, "en")
    mesma_historia = {
        (irma.set.lower(), irma.collector_number.lower())
        for irma in em_ingles
        if irma.flavor_text == carta.flavor_text
    }
    casadas = [
        irma
        for irma in candidatas
        if (irma.set.lower(), irma.collector_number.lower()) in mesma_historia
    ]
    if not casadas:
        logger.info(
            "%s: nenhuma impressao em portugues conta a mesma historia, deixando a em ingles",
            carta.nome_exibido,
        )
        return None
    return max(casadas, key=lambda irma: irma.released_at or date.min).flavor_text


async def find_card_by_id(card_id: str) -> ScryfallCard:
    async with _cliente() as client:
        resposta = await _get(client, f"/cards/{card_id}")
        if resposta.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(f'Impressao "{card_id}" nao encontrada')
        if resposta.status_code != httpx.codes.OK:
            raise UpstreamError(f"O Scryfall respondeu {resposta.status_code}.")
        carta = ScryfallCard.model_validate(resposta.json())
        await _enriquecer_com_arena([carta])
        return carta


async def suggest_names(trecho: str, limite: int = 15) -> list[str]:
    """Nomes que completam o trecho digitado, em portugues.

    O /cards/autocomplete do Scryfall so conhece nome em ingles, entao a
    sugestao sai da busca normal e o autocomplete fica de reserva.
    """
    async with _cliente() as client:
        achadas = await _buscar(client, trecho, "pt", unique="cards")
        if achadas:
            return [c.nome_exibido for c in achadas[:limite]]

        resposta = await _get(client, "/cards/autocomplete", {"q": trecho})
        if resposta.status_code != httpx.codes.OK:
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
    if resposta.status_code != httpx.codes.OK:
        return False
    return resposta.json().get("total_cards", 0) > 0


async def list_sets(limite: int = 60, so_com_portugues: bool = True) -> list[dict]:
    """Edicoes pro fluxo de gerar carta escolhendo a colecao.

    Fora da lista: colecao digital, de token e afins. Com `so_com_portugues`,
    tambem as edicoes sem NENHUMA carta em portugues - verificado uma a uma,
    porque promo e colecao especial anterior ao corte tambem podem nao ter.

    A data do corte entra so como primeiro filtro, pra nao gastar requisicao
    com as dezenas lancadas depois dele. O `/sets` vem do mais recente pro mais
    antigo, entao a verificacao para ao juntar `limite` edicoes, e roda em
    lotes concorrentes (ver TAMANHO_DO_LOTE).
    """
    async with _cliente() as client:
        resposta = await _get(client, "/sets")
        if resposta.status_code != httpx.codes.OK:
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

        if not so_com_portugues:
            return [_edicao_para_dict(s) for s in candidatas[:limite]]

        edicoes = []

        for inicio in range(0, len(candidatas), TAMANHO_DO_LOTE):
            if len(edicoes) >= limite:
                break
            lote = candidatas[inicio : inicio + TAMANHO_DO_LOTE]
            resultados = await asyncio.gather(*(_tem_impressao_pt(client, s["code"]) for s in lote))
            for s, tem_pt in zip(lote, resultados, strict=True):
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
