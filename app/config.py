import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent

PORT = int(os.environ.get("PORT", "8000"))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
# HEADLESS=false abre a janela do Chrome pra debug visual (default: headless, sem janela)
HEADLESS = os.environ.get("HEADLESS", "true").strip().lower() not in ("false", "0", "")

# Fork do Card Conjurer auto-hospedado - nao existe no script-yugioh-maker, la
# o gerador e um site de terceiro; aqui ele roda local.
CARDCONJURER_DIR = Path(os.environ.get("CARDCONJURER_DIR", "vendor/cardconjurer"))
if not CARDCONJURER_DIR.is_absolute():
    CARDCONJURER_DIR = RAIZ / CARDCONJURER_DIR
CARDCONJURER_PORT = int(os.environ.get("CARDCONJURER_PORT", "4242"))
CARDCONJURER_URL = f"http://127.0.0.1:{CARDCONJURER_PORT}"

# O Scryfall pede um User-Agent identificavel em vez de chave de API.
SCRYFALL_USER_AGENT = os.environ.get("SCRYFALL_USER_AGENT", "script-magic-maker/0.1.0")

# Cache dos bancos de carta do MTG Arena (mtgatool-metadata) - traducao pt de
# carta pos-corte, que o Scryfall nao tem. Fica em vendor/ pelo mesmo motivo
# do Card Conjurer: dado de terceiro baixado, fora do controle de versao.
ARENA_CACHE_DIR = Path(os.environ.get("ARENA_CACHE_DIR", "vendor/arena"))
if not ARENA_CACHE_DIR.is_absolute():
    ARENA_CACHE_DIR = RAIZ / ARENA_CACHE_DIR
ARENA_CACHE_MAX_DIAS = int(os.environ.get("ARENA_CACHE_MAX_DIAS", "7"))

# Cache do indice de decks pre-construidos (MTGJSON) - mesmo motivo do cache
# do Arena acima, so que o dado aqui muda bem menos (so quando sai produto
# novo), entao o prazo padrao e maior.
ESTRUTURAIS_CACHE_DIR = Path(os.environ.get("ESTRUTURAIS_CACHE_DIR", "vendor/estruturais"))
if not ESTRUTURAIS_CACHE_DIR.is_absolute():
    ESTRUTURAIS_CACHE_DIR = RAIZ / ESTRUTURAIS_CACHE_DIR
ESTRUTURAIS_CACHE_MAX_DIAS = int(os.environ.get("ESTRUTURAIS_CACHE_MAX_DIAS", "14"))
