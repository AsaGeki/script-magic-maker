# script-magic-maker

Busca os dados oficiais de uma carta de Magic: The Gathering (traduzidos pra
português) na [API do Scryfall](https://scryfall.com/docs/api) e usa Playwright
pra preencher sozinho uma instância local do
[Card Conjurer](https://github.com/Investigamer/cardconjurer): nome, custo de
mana, linha de tipo, texto de regras, flavor, poder/resistência, lealdade,
raridade, símbolo de expansão e a arte da carta. Cobre carta avulsa, deck
importado e deck montado na mão.

Irmão do [script-yugioh-maker](https://github.com/AsaGeki/script-yugioh-maker):
mesma estrutura de módulos, mesmo menu, mesma API de consulta, mesma folha de
impressão. O que muda é a franquia e, com ela, a fonte de dados, o gerador de
imagem e a fonte de arte.

> A API FastAPI incluída aqui é só consulta de dados (pra conferir antes de
> gerar) — quem preenche e baixa a carta é o CLI.

## Por que não baixar a imagem pronta do Scryfall

Porque o resultado imprime pior. A imagem oficial do Scryfall é 745x1040
(~0,77 megapixel, cerca de 298 DPI numa carta de 63,5 x 88,9 mm). O Card
Conjurer renderiza em 1500x2100 (~3,15 megapixels, cerca de 600 DPI) — quatro
vezes mais pixels. Como o objetivo aqui é carta pronta pra impressão, vale
gerar em vez de baixar.

## Stack

- Python 3.13+
- FastAPI (API de consulta de dados)
- Playwright (automação do navegador)
- Typer, questionary, rich (CLI interativo)
- Pydantic (validação dos dados da API oficial)
- pyfiglet e term-image (banner e arte da carta no terminal)
- Pillow e img2pdf (folha de impressão e PDF)
- uv (gerenciador de pacotes)

## Como rodar

Pré-requisitos: Python 3.13+, [`uv`](https://docs.astral.sh/uv/), Git e ~5 GB
de disco livre pro Card Conjurer (2,5 GB de molduras mais o `.git` do clone).

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

O Card Conjurer é baixado à parte, pra `vendor/cardconjurer` (fora do
controle de versão — são 2,7 GB de molduras):

```bash
uv run cli.py setup
```

Depois é só rodar:

```bash
uv run cli.py
```

Sem argumento abre o menu interativo, com três categorias — **Cartas** (por
nome, por termo ou escolhendo a edição), **Decks** (importa a lista) e **PDF**
(monta a folha ou tira uma prova de 1 folha). A moldura sai detectada sozinha a
partir da impressão escolhida (época do frame, borderless, arte estendida,
full art) — só pergunta se você quiser trocar. `cli.py fill "nome"` gera
direto, sem menu. O servidor local do Card Conjurer sobe e desce sozinho junto da
automação.

Importando um deck ainda dá pra escolher a impressão das cartas que a lista
deixou sem edição (ver [DECK.md](DECK.md)) e gerar junto as fichas que as
cartas criam — a quantidade de cada ficha é sempre perguntada, porque a carta
diz que cria ficha, não quantas você vai querer na mesa.

Os demais comandos:

| Comando | O que faz |
|---|---|
| `cli.py setup` | Clona o Card Conjurer em `vendor/` |
| `cli.py serve` | Sobe a API de consulta dos dados |

Formato esperado da lista de deck (`.txt`/`.dec`): ver [DECK.md](DECK.md).

As imagens caem em `output/cards/` (carta avulsa) e `output/decks/<deck>/`
(lista importada); o PDF fica na raiz de `output/`.

Nenhuma variável em `.env` é obrigatória — `PORT`, `OUTPUT_DIR`, `HEADLESS`,
`CARDCONJURER_DIR`, `CARDCONJURER_PORT` e `SCRYFALL_USER_AGENT` já têm default.

## Sobre

Meu nome é Arthur Gabriel e este projeto veio com a ideia de facilitar a
sintetização de cartas de Magic em português e com boa qualidade.
Também feito para organizá-las e deixar pronto para impressão.

Vale dizer: a Wizards parou de imprimir Magic em português depois de Modern
Horizons 3, em 2024. Boa parte da graça disso aqui é justamente conseguir
carta em português de coisa que nunca saiu em português.

## Créditos

Este projeto não seria possível sem estes serviços e projetos de terceiros:

- **[Scryfall](https://scryfall.com)** — API oficial com os dados de cada carta.
- **[Card Conjurer](https://github.com/Investigamer/cardconjurer)** — motor de geração da imagem (fork usado aqui, auto-hospedado).
- **[MTGJSON](https://mtgjson.com)** — índice dos decks pré-construídos oficiais.
- **[mtgatool-metadata](https://github.com/mtgatool/mtgatool-metadata)** — banco de tradução PT do MTG Arena (GPL-3.0).
- **[MTGPics](https://www.mtgpics.com)** — fonte de arte em alta resolução.

Magic: The Gathering é marca registrada da Wizards of the Coast. Este projeto não é afiliado a ela.

---

Feito com esforço por [AsaGeki](https://github.com/AsaGeki) 🐧❤️
