"""Modelos da carta como o Scryfall devolve.

Os nomes de campo são os da API, sem traduzir, pra dar pra conferir contra a
documentação oficial. Campos não declarados são descartados (extra="ignore").
"""

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.cards.arena import TraducaoArena
from app.cards.enums import Layout, Rarity


class FaceBase(BaseModel):
    """Os campos que carta e face têm em comum.

    Carta de dupla face não traz os campos traduzidos no nível de cima: eles
    vivem só dentro de card_faces. Herdando daqui, as duas respondem ao mesmo
    fallback de idioma.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    printed_name: str | None = None
    mana_cost: str | None = None
    type_line: str | None = None
    printed_type_line: str | None = None
    oracle_text: str | None = None
    printed_text: str | None = None
    flavor_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    colors: list[str] | None = None
    artist: str | None = None
    illustration_id: str | None = None
    # As chaves variam com o tempo (hoje: art, art_crop, png, large, normal...),
    # por isso fica como dicionário em vez de modelo fechado.
    image_uris: dict[str, str] | None = None

    @property
    def nome_exibido(self) -> str:
        """Nome traduzido quando existe.

        printed_name às vezes vem em inglês mesmo numa impressão em português.
        """
        return self.printed_name or self.name

    @property
    def tipo_exibido(self) -> str | None:
        return self.printed_type_line or self.type_line

    @property
    def texto_exibido(self) -> str | None:
        return self.printed_text or self.oracle_text

    @property
    def art_crop(self) -> str | None:
        """Recorte da arte do Scryfall — o fallback de arte, 626x457."""
        return (self.image_uris or {}).get("art_crop")


class CardFace(FaceBase):
    """Uma face de carta de dupla face, split, flip ou adventure."""

    color_indicator: list[str] | None = None


class ScryfallCard(FaceBase):
    """A carta como a API devolve."""

    id: str
    oracle_id: str | None = None
    lang: str
    layout: Layout
    rarity: Rarity
    set: str
    set_name: str
    collector_number: str
    released_at: date | None = None
    card_faces: list[CardFace] | None = None

    # Campo nosso: quantas cópias o deck pede, usado pela folha de impressão.
    copias: int = 1

    # Também nosso: tradução do MTG Arena (ver app.cards.arena), preenchida
    # depois da consulta. Cobre carta pós-corte, que só saiu em português no
    # jogo digital.
    arena: TraducaoArena | None = None

    # Extras que ajudam a escolher moldura caso um dia isso saia do autoFrame.
    cmc: float | None = None
    color_identity: list[str] | None = None
    frame: str | None = None
    border_color: str | None = None
    full_art: bool = False
    frame_effects: list[str] | None = None
    promo: bool = False
    promo_types: list[str] | None = None
    textless: bool = False
    finishes: list[str] | None = None
    # Selo holográfico do rodapé: o formato ("oval", "triangle", "acorn"...) ou
    # null quando a impressão não leva selo.
    security_stamp: str | None = None

    # Só vanguard usa: quanto a carta muda o tamanho da mão inicial e o total de
    # vida. Vêm como texto com sinal ("+1", "-8"), que é como a carta imprime.
    hand_modifier: str | None = None
    life_modifier: str | None = None

    @property
    def traduzida(self) -> bool:
        """Se esta impressão é a versão em português.

        Checa o idioma da impressão, não a presença de printed_name: uma carta
        em português pode manter o nome em inglês.
        """
        return self.lang == "pt"

    @property
    def faces(self) -> list[FaceBase]:
        """As faces a gerar. Carta de uma face só devolve ela mesma."""
        return list(self.card_faces) if self.card_faces else [self]

    @property
    def arte_mtgpics(self) -> str:
        """Arte no MTGPics, a fonte primária.

        O número de colecionador nem sempre é numérico (promo e variante têm
        sufixo); aí a URL sai com o valor cru e quem baixa trata o 404.
        """
        numero = self.collector_number
        url = f"https://www.mtgpics.com/pics/art/{self.set}/"
        return f"{url}{int(numero):03d}.jpg" if numero.isdigit() else f"{url}{numero}.jpg"
