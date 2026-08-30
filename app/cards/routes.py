from fastapi import APIRouter, Query

from app.cards.models import ScryfallCard
from app.cards.service import (
    find_card_by_id,
    find_card_by_name,
    search_cards,
    suggest_names,
)
from app.response import ApiResponse

router = APIRouter()


# GET /cards/{name} -> busca carta oficial pelo nome em portugues, retorna dados ja em PT
@router.get("/cards/{name}", response_model=ApiResponse[ScryfallCard])
async def get_card(name: str, ingles: bool = Query(False)):
    carta = await find_card_by_name(name, permitir_ingles=ingles)
    return ApiResponse(message="Carta encontrada!", data=carta)


# GET /cards/{name}/prints -> todas as impressoes daquele nome
@router.get("/cards/{name}/prints", response_model=ApiResponse[list[ScryfallCard]])
async def get_prints(name: str, lang: str = Query("pt")):
    impressoes = await search_cards(name, lang=lang)
    return ApiResponse(message=f"{len(impressoes)} impressoes", data=impressoes)


# GET /prints/{card_id} -> 1 impressao especifica pelo id do Scryfall
@router.get("/prints/{card_id}", response_model=ApiResponse[ScryfallCard])
async def get_print(card_id: str):
    return ApiResponse(message="Impressao encontrada!", data=await find_card_by_id(card_id))


# GET /autocomplete?q= -> nomes em portugues que completam o trecho
@router.get("/autocomplete", response_model=ApiResponse[list[str]])
async def get_autocomplete(q: str = Query(min_length=2)):
    nomes = await suggest_names(q)
    return ApiResponse(message=f"{len(nomes)} sugestoes", data=nomes)
