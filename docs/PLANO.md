# Plano geral

Documento de referência do desenho do `script-magic-maker`. Cobre o objetivo,
as decisões já fechadas, a arquitetura, as fases de implementação e o que
segue em aberto.

Para o levantamento que sustenta as decisões, veja [PESQUISA.md](PESQUISA.md).
Para os detalhes técnicos do gerador, veja [CARDCONJURER.md](CARDCONJURER.md).

## Objetivo

Gerar imagem de carta de Magic: The Gathering em português, em resolução boa o
suficiente pra impressão, a partir do nome da carta ou de uma lista de deck.
Organizar o resultado em pastas e montar o PDF de impressão.

O projeto é o irmão do `script-yugioh-maker`: mesma estrutura, mesmo CLI, mesma
API de consulta. O que muda é a franquia e, com ela, as três peças externas —
a fonte de dados, o gerador de imagem e a fonte de arte.

## Decisões fechadas

Todas em 27/08/2026.

| Assunto | Decisão | Por quê |
|---|---|---|
| Gerador de imagem | Card Conjurer (fork `Investigamer`) auto-hospedado | Importa carta em português nativamente, escolhe moldura sozinho, renderiza em 600 DPI |
| Como dirigir o gerador | Playwright | O Card Conjurer renderiza em `<canvas>` no navegador; não existe API nem CLI |
| Onde fica o fork | `vendor/cardconjurer`, ignorado no git | Tudo num lugar só; 2,7 GB não entram no controle de versão |
| Fonte de dados | Scryfall (`lang:pt`), MTGJSON como apoio offline | Sem chave, sem cadastro, já traz os campos `printed_*` |
| Fonte de arte | MTGPics primário, `art_crop` do Scryfall como fallback | 1920x1080 contra 626x457 |
| API FastAPI | Mantida | Espelha o `script-yugioh-maker`: consulta de leitura pra conferir os dados antes de gerar |
| Carta sem português | O CLI pergunta: gera em inglês ou pula | Dá controle sem travar o fluxo |

### Decisão engavetada: baixar a imagem pronta do Scryfall

Para as ~25.300 cartas que já têm impressão em português, o Scryfall entrega o
PNG oficial direto em `image_uris.png`, dispensando navegador por completo.

Ficou de fora como caminho principal por causa da resolução:

| | Scryfall PNG | Card Conjurer |
|---|---|---|
| Dimensões | 745 x 1040 | 1500 x 2100 |
| Megapixels | 0,77 | 3,15 |
| DPI em 63,5 x 88,9 mm | ~298 | ~600 |
| Moldura | a da impressão original | qualquer uma do catálogo |
| Arte | a da impressão original | trocável |
| Carta sem impressão em português | não existe | gera |

Vale retomar como **modo rápido opcional** (uma flag no CLI) se em algum
momento a prioridade for velocidade em vez de qualidade de impressão. Não
requer nada do que já está desenhado — é um caminho paralelo curto.

## Arquitetura

Espelha o `script-yugioh-maker` módulo a módulo:

```
app/
  cards/      consulta ao Scryfall, modelos Pydantic, enums, rotas da API
  cli/        menu interativo, preview no terminal, configuração de stdio
  deck/       importação de listas de deck e resolução carta a carta
  maker/      automação do Card Conjurer via Playwright
  vendor/     ciclo de vida do fork: download, servidor local, saúde
  print/      layout da folha e geração do PDF de impressão
  config.py   leitura do .env
  errors.py   exceções da aplicação
  main.py     aplicação FastAPI
cli.py        ponto de entrada do Typer
vendor/       clone do Card Conjurer (ignorado no git)
output/       imagens geradas (ignorado no git)
```

O módulo `app/vendor/` não existe no projeto do Yu-Gi-Oh — é o preço de
auto-hospedar. Ele cuida de clonar o fork na primeira execução, subir um
servidor estático na porta configurada e derrubá-lo no fim.

O módulo `app/print/` deve reaproveitar quase inteiro o equivalente do
Yu-Gi-Oh: carta de Magic e carta de Yu-Gi-Oh têm o mesmo tamanho físico
(63,5 x 88,9 mm), então o layout da folha não muda.

### Modelos

Quatro definições em `app/cards/`, com os nomes de campo iguais aos do
Scryfall (sem traduzir), pelo mesmo motivo que o projeto do Yu-Gi-Oh manteve
`atk`/`def_`/`card_images`: facilita conferir contra a documentação oficial.

- **`ScryfallCard`** — a carta como a API devolve: `id`, `oracle_id`, `name`,
  `printed_name`, `lang`, `layout`, `mana_cost`, `type_line`,
  `printed_type_line`, `oracle_text`, `printed_text`, `flavor_text`, `power`,
  `toughness`, `loyalty`, `colors`, `rarity`, `set`, `set_name`,
  `collector_number`, `released_at`, `artist`, `illustration_id`,
  `image_uris`, `card_faces`.
- **`CardFace`** — os mesmos campos, por face. Necessário porque carta de dupla
  face **não traz `printed_*` no nível de cima**: eles vivem só dentro de
  `card_faces`. Verificado no *Delver of Secrets* em português.
- **`Layout`** (enum) — `normal`, `transform`, `modal_dfc`, `split`,
  `adventure`, `saga`, `class`, `flip`, `token`, `planeswalker` e afins.
  Governa qual moldura usar e quantas imagens sair.
- **`Rarity`** (enum) — `common`, `uncommon`, `rare`, `mythic`, `special`,
  `bonus`. Vai no símbolo de expansão.

`ScryfallCard` expõe uma propriedade que resolve o fallback de idioma num lugar
só — devolve o texto em português quando existe e sinaliza quando falta, pra
que o CLI possa perguntar o que fazer. Evita espalhar condicional de idioma
pelo código todo.

## Fluxo de geração

1. O CLI recebe um nome de carta ou uma lista de deck.
2. `app/cards/` busca no Scryfall com `lang:pt`.
3. Se não houver impressão em português, o CLI pergunta: gerar em inglês ou
   pular a carta.
4. `app/vendor/` garante que o Card Conjurer está baixado e servindo.
5. `app/maker/` abre a página no Playwright e, em vez de preencher campo a
   campo, chama as funções globais do próprio Card Conjurer via `evaluate` —
   ele já sabe importar do Scryfall no idioma escolhido, baixar a arte e
   escolher a moldura. Detalhes em [CARDCONJURER.md](CARDCONJURER.md).
6. A imagem é lida do canvas e salva em `output/`.
7. Opcionalmente, `app/print/` monta o PDF de impressão.

A diferença de esforço em relação ao projeto do Yu-Gi-Oh está no passo 5. Lá
foi preciso mapear 29 tipos de carta para subtipo e traços, calcular tamanho de
fonte na mão e quebrar linha manualmente porque o site não redimensionava nada.
Aqui o Card Conjurer faz layout de texto, escala de fonte e escolha de moldura
sozinho.

## Fases

- [ ] **1. Esqueleto** — `pyproject.toml`, `.env.example`, `.gitignore` com
  `vendor/`, `app/config.py`, `app/errors.py`, `cli.py` mínimo.
- [ ] **2. Dados** — `app/cards/`: modelos, enums, cliente do Scryfall, busca
  por nome com `lang:pt` e detecção de ausência de português.
- [ ] **3. API** — `app/main.py` e `app/cards/routes.py`: consulta de leitura
  pra conferir os dados antes de gerar.
- [ ] **4. Vendor** — `app/vendor/`: clone do fork, servidor estático local,
  verificação de saúde, encerramento limpo.
- [ ] **5. Maker** — `app/maker/`: automação do Card Conjurer, carta avulsa
  primeiro, depois dupla face e demais layouts.
- [ ] **6. CLI** — menu interativo, preview no terminal, a pergunta de idioma
  quando faltar português.
- [ ] **7. Decks** — importação de lista e geração em lote reaproveitando um
  navegador só.
- [ ] **8. Impressão** — `app/print/`, portado do projeto do Yu-Gi-Oh.

## Em aberto

- **Layouts além do `normal`.** Dupla face, split, adventure, saga e
  planeswalker têm forma própria e vão precisar de tratamento caso a caso no
  `app/maker/`. A fase 5 começa só pelo `normal`.
- **De onde importar deck.** Moxfield e Archidekt têm API; o formato `.dec` em
  texto puro é o mínimo. A decidir na fase 7.
- **Cartas pós-Modern Horizons 3.** Sem tradução oficial em papel. A decisão de
  hoje é perguntar no CLI; se um dia isso incomodar, a saída é extrair a
  localização pt-BR do MTG Arena. Ver [PESQUISA.md](PESQUISA.md).
- **Peso do `vendor/`.** 2,7 GB. Se virar problema, dá pra fazer clone parcial
  só das molduras em uso (~580 MB usando a família M15).
