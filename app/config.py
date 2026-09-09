import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent

PORT = int(os.environ.get("PORT", "8000"))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
# HEADLESS=false abre a janela do Chrome pra debug visual (default: headless, sem janela)
HEADLESS = os.environ.get("HEADLESS", "true").strip().lower() not in ("false", "0", "")

# Fork do Card Conjurer, auto-hospedado.
CARDCONJURER_DIR = Path(os.environ.get("CARDCONJURER_DIR", "vendor/cardconjurer"))
if not CARDCONJURER_DIR.is_absolute():
    CARDCONJURER_DIR = RAIZ / CARDCONJURER_DIR
CARDCONJURER_PORT = int(os.environ.get("CARDCONJURER_PORT", "4242"))
CARDCONJURER_URL = f"http://127.0.0.1:{CARDCONJURER_PORT}"

# O Scryfall pede um User-Agent identificavel em vez de chave de API.
SCRYFALL_USER_AGENT = os.environ.get("SCRYFALL_USER_AGENT", "script-magic-maker/0.1.0")

# Bancos do MTG Arena (mtgatool-metadata): traducao pt de carta pos-corte. Em
# vendor/ porque e dado de terceiro baixado, fora do controle de versao.
ARENA_CACHE_DIR = Path(os.environ.get("ARENA_CACHE_DIR", "vendor/arena"))
if not ARENA_CACHE_DIR.is_absolute():
    ARENA_CACHE_DIR = RAIZ / ARENA_CACHE_DIR
ARENA_CACHE_MAX_DIAS = int(os.environ.get("ARENA_CACHE_MAX_DIAS", "7"))

# Indice de decks pre-construidos (MTGJSON). Muda so quando sai produto novo,
# por isso o prazo maior.
ESTRUTURAIS_CACHE_DIR = Path(os.environ.get("ESTRUTURAIS_CACHE_DIR", "vendor/estruturais"))
if not ESTRUTURAIS_CACHE_DIR.is_absolute():
    ESTRUTURAIS_CACHE_DIR = RAIZ / ESTRUTURAIS_CACHE_DIR
ESTRUTURAIS_CACHE_MAX_DIAS = int(os.environ.get("ESTRUTURAIS_CACHE_MAX_DIAS", "14"))

# Acervo completo do MTGJSON (AllPrintings.sqlite), consultado quando o
# Scryfall limita requisicao. Sao ~650 MB em disco, baixados so na primeira vez
# que a saida e usada.
MTGJSON_CACHE_DIR = Path(os.environ.get("MTGJSON_CACHE_DIR", "vendor/mtgjson"))
if not MTGJSON_CACHE_DIR.is_absolute():
    MTGJSON_CACHE_DIR = RAIZ / MTGJSON_CACHE_DIR
MTGJSON_CACHE_MAX_DIAS = int(os.environ.get("MTGJSON_CACHE_MAX_DIAS", "30"))
