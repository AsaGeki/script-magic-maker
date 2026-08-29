"""Exceções da aplicação.

Todas descendem de ErroDoApp, então o CLI e a API conseguem capturar num ponto
só e mostrar a mensagem — que já vem em português, pronta pro usuário final.
"""


class ErroDoApp(Exception):
    """Base de todo erro previsto do projeto."""


# --- Scryfall / dados da carta ---


class ErroDoScryfall(ErroDoApp):
    """Falha ao falar com a API do Scryfall."""


class CartaNaoEncontrada(ErroDoApp):
    def __init__(self, nome: str) -> None:
        self.nome = nome
        super().__init__(f"Carta não encontrada no Scryfall: {nome!r}.")


class SemVersaoEmPortugues(ErroDoApp):
    def __init__(self, nome: str) -> None:
        self.nome = nome
        super().__init__(f"A carta {nome!r} não tem impressão em português.")


# --- Card Conjurer (vendor) ---


class ErroDoCardConjurer(ErroDoApp):
    """Falha na automação ou no servidor local do Card Conjurer."""


class CardConjurerNaoInstalado(ErroDoCardConjurer):
    def __init__(self, caminho: str) -> None:
        self.caminho = caminho
        super().__init__(
            f"Card Conjurer não encontrado em {caminho}. Rode 'uv run cli.py setup' primeiro."
        )


# --- Deck ---


class ErroDeDeck(ErroDoApp):
    """Lista de deck inválida ou que não pôde ser resolvida."""
