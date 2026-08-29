"""Enums dos campos fechados do Scryfall.

Os valores são exatamente os que a API devolve, sem traduzir, pra dar pra
conferir contra a documentação oficial.
"""

from enum import StrEnum


class Layout(StrEnum):
    """Forma da carta. Governa qual moldura usar e quantas imagens sair.

    Tolerante de propósito: o Scryfall acrescenta layout quando sai mecânica
    nova (battle e case são recentes), e uma carta com layout desconhecido não
    pode travar a consulta. Cai em UNKNOWN e quem for gerar a imagem avisa que
    não sabe tratar aquele formato.
    """

    NORMAL = "normal"
    SPLIT = "split"
    FLIP = "flip"
    TRANSFORM = "transform"
    MODAL_DFC = "modal_dfc"
    MELD = "meld"
    LEVELER = "leveler"
    CLASS = "class"
    CASE = "case"
    SAGA = "saga"
    ADVENTURE = "adventure"
    MUTATE = "mutate"
    PROTOTYPE = "prototype"
    BATTLE = "battle"
    PLANAR = "planar"
    SCHEME = "scheme"
    VANGUARD = "vanguard"
    TOKEN = "token"
    DOUBLE_FACED_TOKEN = "double_faced_token"
    EMBLEM = "emblem"
    AUGMENT = "augment"
    HOST = "host"
    ART_SERIES = "art_series"
    REVERSIBLE_CARD = "reversible_card"

    # Layout que a API passou a devolver depois desta lista.
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> "Layout":
        return cls.UNKNOWN


class Rarity(StrEnum):
    """Raridade da impressão. Vai no símbolo de expansão."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    MYTHIC = "mythic"
    SPECIAL = "special"
    BONUS = "bonus"

    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> "Rarity":
        return cls.UNKNOWN
