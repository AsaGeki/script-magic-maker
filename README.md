# script-magic-maker

> **Em construção.** Nada implementado ainda — por enquanto só a pesquisa e o
> desenho estão prontos. Veja [docs/PLANO.md](docs/PLANO.md) para o plano de
> implementação e o estado de cada etapa.

Busca os dados oficiais de uma carta de Magic: The Gathering (traduzidos pra
português) na [API do Scryfall](https://scryfall.com/docs/api) e usa Playwright
pra preencher sozinho uma instância local do
[Card Conjurer](https://github.com/Investigamer/cardconjurer): nome, custo de
mana, linha de tipo, texto de regras, flavor, poder/resistência, lealdade,
raridade, símbolo de expansão e a arte da carta. Cobre carta avulsa, deck
importado e deck montado na mão.

Irmão do [script-yugioh-maker](https://github.com/AsaGeki/script-yugioh-maker),
com as mesmas ideias e outra franquia.

> A API FastAPI incluída aqui é só consulta de dados (pra conferir antes de
> gerar) — quem preenche e baixa a carta é o CLI.

## Por que não baixar a imagem pronta do Scryfall

Porque o resultado imprime pior. A imagem oficial do Scryfall é 745x1040
(~0,77 megapixel, cerca de 298 DPI numa carta de 63,5 x 88,9 mm). O Card
Conjurer renderiza em 1500x2100 (~3,15 megapixels, cerca de 600 DPI) — quatro
vezes mais pixels. Como o objetivo aqui é carta pronta pra impressão, vale
gerar em vez de baixar.

O atalho não foi descartado, só engavetado: está registrado em
[docs/PLANO.md](docs/PLANO.md) como possível modo rápido opcional.

## Stack

- Python 3.13+
- FastAPI (API de consulta de dados)
- Playwright (automação do navegador)
- Typer, questionary, rich (CLI interativo)
- Pydantic (validação dos dados da API oficial)
- uv (gerenciador de pacotes)

## Como rodar

Pré-requisitos: Python 3.13+, [`uv`](https://docs.astral.sh/uv/), Git e ~3 GB
de disco livre pro Card Conjurer.

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

Sem argumento abre o menu interativo (Cartas/Decks); `cli.py fill "nome"` gera
direto, sem menu. O servidor local do Card Conjurer sobe e desce sozinho junto
da automação.

Nenhuma variável em `.env` é obrigatória — `PORT`, `OUTPUT_DIR`, `HEADLESS`,
`CARDCONJURER_DIR` e `CARDCONJURER_PORT` já têm default.

## Documentação

- [docs/PLANO.md](docs/PLANO.md) — arquitetura, módulos, fases de implementação
  e o que ainda está em aberto.
- [docs/PESQUISA.md](docs/PESQUISA.md) — os geradores de carta avaliados, as
  fontes de texto em português e as fontes de arte, com as medições que
  sustentam cada escolha.
- [docs/CARDCONJURER.md](docs/CARDCONJURER.md) — notas técnicas do Card
  Conjurer: funções globais, identificadores do DOM, pegadinhas e o fluxo de
  automação recomendado.

## Sobre

Meu nome é Arthur Gabriel e este projeto veio com a ideia de facilitar a
sintetização de cartas de Magic em português e com boa qualidade.
Também feito para organizá-las e deixar pronto para impressão.

Vale dizer: a Wizards parou de imprimir Magic em português depois de Modern
Horizons 3, em 2024. Boa parte da graça disso aqui é justamente conseguir
carta em português de coisa que nunca saiu em português.

---

Feito com esforço por [AsaGeki](https://github.com/AsaGeki) 🐧❤️
