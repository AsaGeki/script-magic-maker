"""Aplicação FastAPI.

Consulta de leitura dos dados da carta, pra conferir antes de gerar. A geração
da imagem é do CLI, não daqui.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.cards.routes import router as cards_router
from app.cards.scryfall import ScryfallClient
from app.errors import (
    CartaNaoEncontrada,
    ErroDoApp,
    ErroDoScryfall,
    SemVersaoEmPortugues,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Um cliente do Scryfall só, reaproveitando a conexão entre requisições."""
    app.state.scryfall = ScryfallClient()
    try:
        yield
    finally:
        app.state.scryfall.close()


app = FastAPI(
    title="script-magic-maker",
    description="Consulta os dados oficiais de cartas de Magic em português.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(cards_router)

# Cada erro previsto vira um código HTTP; o resto cai no 500 padrão.
STATUS_POR_ERRO: dict[type[ErroDoApp], int] = {
    CartaNaoEncontrada: 404,
    SemVersaoEmPortugues: 409,
    ErroDoScryfall: 502,
}


@app.exception_handler(ErroDoApp)
async def tratar_erro_do_app(request: Request, erro: ErroDoApp) -> JSONResponse:
    status = STATUS_POR_ERRO.get(type(erro), 500)
    return JSONResponse(status_code=status, content={"detail": str(erro)})


@app.get("/health", tags=["infra"], summary="Sinal de vida")
def health() -> dict[str, str]:
    return {"status": "ok"}
