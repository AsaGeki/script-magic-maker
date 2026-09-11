"""Orquestra o fluxo de deck: da lista em texto ate as cartas resolvidas no
Scryfall. Sem nenhum questionary aqui - quem pergunta e o menu (app.cli.menu).
"""

import asyncio
import logging

from app.cards.models import ScryfallCard
from app.cards.service import (
    completar_traducao_pos_corte,
    e_terreno_basico,
    find_card_by_name,
    find_card_by_print,
)
from app.deck.texto import EntradaDeDeck
from app.errors import AppError
from app.slug import slug

logger = logging.getLogger(__name__)

# Quantas linhas da lista sao resolvidas ao mesmo tempo. O ritmo entre as
# requisicoes e global (ver app.rede.respeitar_ritmo), entao o paralelismo
# sobrepoe a espera da rede sem furar o limite do Scryfall.
CONSULTAS_SIMULTANEAS = 5


async def buscar_cartas_do_deck(
    entradas: list[EntradaDeDeck], permitir_ingles: bool = True
) -> tuple[list[tuple[EntradaDeDeck, ScryfallCard]], list[str]]:
    """Traduz cada entrada da lista numa carta do Scryfall.

    Retorna (pares, avisos), cada par com a entrada que originou a carta - e
    a entrada que diz se a linha travou a impressao ou nao, e quem quiser
    reescrever a linha depois precisa dela. Uma entrada que falha vira aviso e
    as outras seguem: lista de deck com 1 nome errado nao pode derrubar o lote
    inteiro.

    Linha que travou uma impressao e recebeu outra tambem vira aviso: o codigo
    pode estar errado (SDL no lugar de SLD) ou a impressao pode nao existir em
    portugues, e nos dois casos o deck sai diferente do que a lista pediu.
    """
    semaforo = asyncio.Semaphore(CONSULTAS_SIMULTANEAS)

    async def resolver(entrada: EntradaDeDeck) -> ScryfallCard | str:
        """A carta da linha, ou o aviso que explica por que ela nao veio."""
        async with semaforo:
            try:
                return await _resolver(entrada, permitir_ingles)
            except AppError as erro:
                return f"{entrada.nome}: {erro.message}"

    resultados = await asyncio.gather(*(resolver(entrada) for entrada in entradas))

    pares: list[tuple[EntradaDeDeck, ScryfallCard]] = []
    avisos: list[str] = []
    # A ordem da lista e a ordem do deck: o gather devolve na ordem das entradas.
    for entrada, resultado in zip(entradas, resultados, strict=True):
        if isinstance(resultado, str):
            avisos.append(resultado)
            continue
        if trocada := _impressao_trocada(entrada, resultado):
            avisos.append(trocada)
        resultado.copias = entrada.quantidade
        pares.append((entrada, resultado))

    return pares, avisos


def _impressao_trocada(entrada: EntradaDeDeck, carta: ScryfallCard) -> str | None:
    """Aviso quando a linha travou uma impressao e veio outra."""
    if not entrada.set or not entrada.collector_number:
        return None
    pedida = (entrada.set.lower(), entrada.collector_number.lstrip("0").lower())
    veio = (carta.set.lower(), carta.collector_number.lstrip("0").lower())
    if pedida == veio:
        return None
    return (
        f"{entrada.nome}: a lista pede {entrada.set.upper()} #{entrada.collector_number}, "
        f"mas saiu {carta.set.upper()} #{carta.collector_number}"
    )


def juntar_impressoes_repetidas(cartas: list[ScryfallCard]) -> list[ScryfallCard]:
    """Uma carta por impressao, somando as copias das linhas que cairam nela.

    Duas linhas com impressoes diferentes podem terminar na mesma - por codigo
    de colecao errado ou por a impressao pedida nao existir em portugues. Sem
    juntar, o gerador desenha o mesmo arquivo duas vezes e a segunda passada
    sobrescreve a primeira.
    """
    juntadas: dict[tuple[str, str], ScryfallCard] = {}
    for carta in cartas:
        chave = (carta.set.lower(), carta.collector_number.lower())
        if repetida := juntadas.get(chave):
            repetida.copias += carta.copias
            continue
        juntadas[chave] = carta
    return list(juntadas.values())


async def _resolver(entrada: EntradaDeDeck, permitir_ingles: bool) -> ScryfallCard:
    """Impressao exata quando a linha traz edicao e numero; senao, pelo nome.

    A impressao pedida pode nao ter PT nenhum (ex.: colecao pos-corte de
    traducao). Terreno basico e carta comum aceitam ela mesma assim - a
    primeira porque so a arte importa, a segunda com nome/tipo/regras
    emprestados de uma irma em PT (completar_traducao_pos_corte), pra manter a
    arte pedida em vez de trocar de edicao. So cai pra busca por nome (que
    pode trazer outra edicao) quando nem a impressao pedida em ingles bate com
    o que a linha pede.
    """
    if entrada.set and entrada.collector_number:
        carta = await find_card_by_print(entrada.set, entrada.collector_number)
        if carta is not None and _e_a_carta_da_linha(entrada.nome, carta):
            return carta
        if carta is not None:
            logger.warning(
                '"%s": %s #%s e "%s", nao "%s" - seguindo pelo nome',
                entrada.nome,
                entrada.set.upper(),
                entrada.collector_number,
                carta.nome_exibido,
                entrada.nome,
            )
        else:
            carta_en = await find_card_by_print(entrada.set, entrada.collector_number, lang="en")
            if carta_en is not None and e_terreno_basico(carta_en):
                if _e_o_terreno_basico_pedido(entrada.nome, carta_en):
                    # Terreno basico: so a arte da impressao pedida importa. O
                    # nome definitivo (em PT) vem depois de qualquer irma via
                    # traduzir_terreno_basico - aqui so a cor precisa bater.
                    return carta_en
            elif carta_en is not None:
                # Carta comum sem PT nenhum na impressao pedida: pega nome,
                # tipo e regras da irma PT mais recente e mantem a arte e o
                # resto dos metadados da impressao pedida (ver
                # completar_traducao_pos_corte).
                await completar_traducao_pos_corte(carta_en)
                if _e_a_carta_da_linha(entrada.nome, carta_en):
                    return carta_en
            logger.info(
                '"%s": impressao %s #%s nao encontrada em PT, procurando a carta '
                "em outra edicao antes de cair pro ingles",
                entrada.nome,
                entrada.set.upper(),
                entrada.collector_number,
            )
            try:
                return await find_card_by_name(entrada.nome, permitir_ingles=False)
            except AppError:
                pass
            if (
                permitir_ingles
                and carta_en is not None
                and _e_a_carta_da_linha(entrada.nome, carta_en)
            ):
                return carta_en

    return await find_card_by_name(entrada.nome, permitir_ingles=permitir_ingles)


# As 5 cores de terreno basico, PT e EN - nome oficial da carta, fixo desde
# sempre (nao dado que desatualiza, e' vocabulario do jogo).
_TIPOS_DE_TERRENO_BASICO = {
    "floresta": "Forest",
    "forest": "Forest",
    "ilha": "Island",
    "island": "Island",
    "pantano": "Swamp",
    "swamp": "Swamp",
    "montanha": "Mountain",
    "mountain": "Mountain",
    "planicie": "Plains",
    "plains": "Plains",
}


def _e_o_terreno_basico_pedido(nome_pedido: str, carta: ScryfallCard) -> bool:
    """Se a impressao de terreno basico achada e da mesma cor que a linha pede.

    _e_a_carta_da_linha nao serve aqui: carta ainda em ingles ("Forest") contra
    linha em PT ("Floresta") nunca bate por slug, mesmo sendo a carta certa.
    Sem checar a cor, edicao ou numero errado na lista (ex.: TDM #281 e Swamp,
    nao Mountain) sairia com o terreno errado sem aviso nenhum.
    """
    esperado = _TIPOS_DE_TERRENO_BASICO.get(slug(nome_pedido))
    return esperado is not None and slug(esperado) == slug(carta.name)


def _e_a_carta_da_linha(nome_pedido: str, carta: ScryfallCard) -> bool:
    """Se a impressao achada pela edicao e numero e mesmo a carta que a linha
    nomeia.

    Edicao e numero errados apontam pra outra carta sem dar erro nenhum - a
    consulta acha uma impressao valida, so que nao a pedida. Sem conferir o
    nome, o deck sai com a carta trocada em silencio.

    O slug compara sem acento nem maiuscula, e a face da frente entra sozinha
    pra carta de nome composto, onde a linha costuma trazer so a primeira.
    """
    nomes = set()
    for nome in (carta.name, carta.nome_exibido):
        nomes.add(slug(nome))
        nomes.add(slug(nome.split(" // ")[0]))
    return slug(nome_pedido) in nomes
