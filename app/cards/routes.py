"""Rotas de consulta da carta.

Só leitura: servem pra conferir os dados antes de gerar a imagem. Quem gera
carta é o CLI.

As rotas são `def`, não `async def`, porque o cliente do Scryfall é síncrono —
o FastAPI roda função síncrona em threadpool, sem travar o laço de eventos.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.cards.models import ScryfallCard
from app.cards.scryfall import ScryfallClient

router = APIRouter(prefix="/cards", tags=["cards"])


def get_client(request: Request) -> ScryfallClient:
    """O cliente é criado uma vez no lifespan e vive no estado da aplicação."""
    return request.app.state.scryfall


Cliente = Annotated[ScryfallClient, Depends(get_client)]


@router.get("/autocomplete", summary="Nomes que completam o trecho digitado")
def autocomplete(
    cliente: Cliente,
    q: Annotated[str, Query(min_length=2, description="Trecho do nome da carta")],
    lang: Annotated[str, Query(description="pt usa a busca; qualquer outro, o autocomplete")] = "pt",
) -> list[str]:
    """O autocomplete oficial do Scryfall só fala inglês, daí o desvio em pt."""
    if lang == "pt":
        return cliente.sugerir_em_portugues(q)
    return cliente.sugerir(q)


@router.get("/search", summary="Todas as impressões da carta num idioma")
def search(
    cliente: Cliente,
    q: Annotated[str, Query(min_length=1, description="Nome da carta")],
    lang: Annotated[str, Query(description="Idioma da impressão")] = "pt",
    exato: Annotated[bool, Query(description="Casar o nome inteiro")] = True,
) -> list[ScryfallCard]:
    return cliente.buscar(q, lang=lang, exato=exato)


@router.get("/id/{card_id}", summary="Uma impressão pelo identificador do Scryfall")
def por_id(cliente: Cliente, card_id: str) -> ScryfallCard:
    return cliente.buscar_por_id(card_id)


@router.get("/{nome}", summary="A carta em português, como o gerador vai receber")
def por_nome(
    cliente: Cliente,
    nome: str,
    permitir_ingles: Annotated[
        bool, Query(description="Cai pro inglês quando não houver impressão em português")
    ] = False,
) -> ScryfallCard:
    return cliente.buscar_carta(nome, permitir_ingles=permitir_ingles)
