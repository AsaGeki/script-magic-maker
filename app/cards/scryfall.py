"""Cliente do Scryfall.

Síncrono de propósito: o CLI e o Playwright são síncronos, e a API do FastAPI
usa rota `def` (que já roda em threadpool). Assim não existe versão duplicada
async do mesmo cliente.

A API não pede chave nem cadastro — só um User-Agent identificável e cerca de
100 ms entre requisições, respeitados aqui.
"""

import time

import httpx

from app.cards.models import ScryfallCard
from app.config import settings
from app.errors import CartaNaoEncontrada, ErroDoScryfall, SemVersaoEmPortugues

BASE_URL = "https://api.scryfall.com"
INTERVALO_MINIMO = 0.1  # segundos entre requisições, como o Scryfall pede
TIMEOUT = 30.0


class ScryfallClient:
    """Consulta ao Scryfall com o intervalo entre requisições respeitado."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url=BASE_URL,
            timeout=TIMEOUT,
            headers={
                "User-Agent": settings.scryfall_user_agent,
                "Accept": "application/json",
            },
        )
        self._ultima_requisicao = 0.0

    def __enter__(self) -> "ScryfallClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, caminho: str, params: dict[str, str] | None = None) -> httpx.Response:
        espera = INTERVALO_MINIMO - (time.monotonic() - self._ultima_requisicao)
        if espera > 0:
            time.sleep(espera)
        try:
            resposta = self._client.get(caminho, params=params)
        except httpx.HTTPError as erro:
            raise ErroDoScryfall(f"Falha ao consultar o Scryfall: {erro}") from erro
        finally:
            self._ultima_requisicao = time.monotonic()
        return resposta

    def buscar(
        self,
        nome: str,
        lang: str = "pt",
        exato: bool = True,
        unique: str = "prints",
    ) -> list[ScryfallCard]:
        """Todas as impressões da carta no idioma pedido.

        Lista vazia quando não existe impressão nesse idioma — o 404 do
        /cards/search significa "nenhum resultado", não falha de rede.

        unique="cards" colapsa as várias impressões da mesma carta numa só,
        que é o que serve pra sugerir nome.
        """
        consulta = f'!"{nome}"' if exato else nome
        resposta = self._get(
            "/cards/search", params={"q": f"{consulta} lang:{lang}", "unique": unique}
        )
        if resposta.status_code == 404:
            return []
        if resposta.status_code != 200:
            raise ErroDoScryfall(
                f"O Scryfall respondeu {resposta.status_code} para {nome!r}."
            )
        dados = resposta.json().get("data", [])
        return [ScryfallCard.model_validate(item) for item in dados]

    def buscar_carta(self, nome: str, permitir_ingles: bool = False) -> ScryfallCard:
        """A carta em português, com o inglês como saída opcional.

        Levanta SemVersaoEmPortugues quando só existe em inglês e
        permitir_ingles é falso, pra que o CLI possa perguntar o que fazer.
        """
        impressoes = self.buscar(nome, lang="pt")
        if impressoes:
            return impressoes[0]

        em_ingles = self.buscar(nome, lang="en")
        if not em_ingles:
            raise CartaNaoEncontrada(nome)
        if not permitir_ingles:
            raise SemVersaoEmPortugues(nome)
        return em_ingles[0]

    def buscar_por_id(self, card_id: str) -> ScryfallCard:
        """Uma impressão específica, pelo identificador do Scryfall."""
        resposta = self._get(f"/cards/{card_id}")
        if resposta.status_code == 404:
            raise CartaNaoEncontrada(card_id)
        if resposta.status_code != 200:
            raise ErroDoScryfall(
                f"O Scryfall respondeu {resposta.status_code} para o id {card_id!r}."
            )
        return ScryfallCard.model_validate(resposta.json())

    def buscar_por_impressao(
        self, codigo_da_edicao: str, numero: str, lang: str = "pt"
    ) -> ScryfallCard | None:
        """A impressão exata, quando a lista de deck diz a edição e o número.

        Devolve None quando essa impressão não existe no idioma pedido, pra que
        quem chamou decida se cai pro inglês ou procura pelo nome.
        """
        resposta = self._get(f"/cards/{codigo_da_edicao.lower()}/{numero}/{lang}")
        if resposta.status_code == 404:
            return None
        if resposta.status_code != 200:
            raise ErroDoScryfall(
                f"O Scryfall respondeu {resposta.status_code} para "
                f"{codigo_da_edicao.upper()} #{numero}."
            )
        return ScryfallCard.model_validate(resposta.json())

    def sugerir(self, trecho: str) -> list[str]:
        """Nomes que completam o trecho digitado.

        Atenção: o /cards/autocomplete do Scryfall só conhece nome em inglês —
        buscar "Raio" ali devolve "Samurai of the Pale Curtain", porque casa a
        sequência de letras no nome em inglês. Pra sugerir em português, use
        sugerir_em_portugues().
        """
        resposta = self._get("/cards/autocomplete", params={"q": trecho})
        if resposta.status_code != 200:
            return []
        return resposta.json().get("data", [])

    def sugerir_em_portugues(self, trecho: str, limite: int = 10) -> list[str]:
        """Nomes em português que contêm o trecho digitado.

        Via busca inexata com lang:pt, já que o autocomplete oficial não fala
        português. unique="cards" evita repetir a mesma carta uma vez por
        impressão.
        """
        impressoes = self.buscar(trecho, lang="pt", exato=False, unique="cards")
        return [c.nome_exibido for c in impressoes[:limite]]
