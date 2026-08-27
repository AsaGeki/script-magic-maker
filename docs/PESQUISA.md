# Pesquisa

Levantamento feito em 27/08/2026 para escolher as três peças externas do
projeto: o gerador de imagem, a fonte de texto em português e a fonte de arte.
Os números aqui foram medidos na data, não copiados de documentação.

## 1. Geradores de carta

Critério: qualidade de saída, quanto dá pra personalizar e quão automatizável é
o formulário. Inspecionei o DOM de cada candidato.

### Card Conjurer, fork auto-hospedado — escolhido

Repositório [Investigamer/cardconjurer](https://github.com/Investigamer/cardconjurer),
237 estrelas, último push em agosto de 2024. O site original saiu do ar em 2022
depois de uma notificação extrajudicial da Wizards; o fork existe pra rodar
localmente.

O que pesou:

- **Importa carta em português de fábrica.** Tem um `<select id="import-language">`
  com `<option value="pt">`, e a função `processScryfallCard()` troca sozinha
  `name`, `type_line` e `oracle_text` pelos campos `printed_*` quando o idioma
  não é inglês.
- **Escolhe a moldura sozinho.** O `<select id="autoFrame">` decide pela cor e
  pelo tipo da carta. Sem isso seria preciso mapear na mão as centenas de
  molduras do catálogo — M15, 8th, Seventh, Saga, Planeswalker, Borderless,
  Showcase, Universes Beyond, tokens.
- **Resolução.** Canvas de 1500x2100 na maioria das molduras, 2010x2814 em
  algumas. Cerca de 600 DPI numa carta de 63,5 x 88,9 mm.
- **Automatizável por função, não por clique.** `fetchScryfallData()`,
  `importCard()`, `changeCardIndex()` e `downloadCard()` são funções globais.
  Dá pra chamá-las direto, sem caçar rótulo e clicar campo a campo.
- **Rodando local:** sem limite de requisição, sem termos de uso de terceiro,
  DOM congelado na versão clonada e funciona offline.

O detalhamento técnico está em [CARDCONJURER.md](CARDCONJURER.md).

### MTG.cards — plano B

Sem login, campos com identificador limpo: `#cardName`, `#manaCost`,
`#cardType`, `#description`, `#powerValue`, `#toughnessValue`, `#artistName`,
`#artworkFile`, `#frameCategory`, `#frameColor`, `#scryfallSearch`. É o
formulário mais simples de automatizar entre os avaliados.

Contra: só cinco categorias de moldura (Modern, Vintage, Box Topper, Mystical
Archives, Full Art), é uma loja de impressão de proxy com bastante venda
cruzada, e roda em WordPress com `nonce` — o que significa sessão pra manter.

### Descartados

**cardconjurer.com atual (2026).** Foi reescrito em Angular e virou um editor
de template genérico, com conta e assinatura (`Saved Templates (0/1)`). Perdeu
o import do Scryfall, que é justamente o que interessa. É por isso que o fork
da versão legada é o alvo, e não o site oficial.

**MTGCardBuilder.** O `/creator/` redireciona pra `/login/`; exige conta. O
"1200 DPI" anunciado na home é material de divulgação, não uma medição.

**MTGCardsmith.** Voltado a comunidade e fórum, com qualidade de saída menor.

**Proxyshop.** Qualidade máxima do mercado (templates de Photoshop, 1200 DPI),
mas exige Photoshop e só roda em Windows. Dependência pesada demais pro escopo.

**Magic Set Editor.** Aplicativo de desktop, ótimo pro entusiasta que edita à
mão, ruim pra automação.

## 2. Texto em português

### Scryfall — fonte primária

`https://api.scryfall.com`, sem chave e sem cadastro. Pede apenas um
`User-Agent` identificável e cerca de 100 ms entre requisições.

Busca com `lang:pt` e leitura dos campos `printed_name`, `printed_type_line` e
`printed_text`:

```
GET /cards/search?q=!"Lightning Bolt" lang:pt&unique=prints

printed_name:      "Raio"
printed_type_line: "Mágica Instantânea"
printed_text:      "Raio causa 3 pontos de dano a qualquer alvo."
```

Cobertura medida:

| Métrica | Valor |
|---|---|
| Impressões em português | 39.535 |
| Cartas únicas (por oracle) | 25.303 |
| Impressões posteriores a 01/07/2024 | 1 |

**Atenção com carta de dupla face:** os campos `printed_*` não aparecem no
nível de cima do objeto, só dentro de `card_faces`. Confirmado no *Delver of
Secrets* em português, cujo `printed_text` da face frontal vem traduzido
enquanto o topo do objeto não tem campo `printed_` nenhum. É por isso que
existe um modelo `CardFace` separado.

### MTGJSON — apoio offline

Campo `foreignData` com `language: "Portuguese (Brazil)"`, trazendo `name`,
`text`, `flavorText` e `type`. Teste no arquivo `MH3.json`: 468 das 564 cartas
do set têm entrada em português.

Serve pra montar dicionário local e não bater na API a cada carta.

### O corte de 2024

A Wizards **parou de imprimir Magic em português**. O último set traduzido foi
Modern Horizons 3, no segundo trimestre de 2024
([anúncio oficial](https://magic.wizards.com/en/news/announcements/changes-to-magic-product-languages-in-2024)).
O motivo declarado foi venda abaixo do custo, incluindo o fato de que jogadores
em países lusófonos compravam carta em inglês de qualquer jeito.

O número acima confirma na prática: o Scryfall tem **uma única** impressão em
português posterior a julho de 2024, no banco inteiro.

Consequência direta pro projeto: carta de Foundations em diante não tem texto
oficial em português em papel nenhum. As saídas são:

1. **Deixar em inglês** — simples e honesto.
2. **Localização pt-BR do MTG Arena** — o Arena segue traduzido. As strings
   ficam nos arquivos `data_loc_*.mtga` e `data_cards_*.mtga`, já parseados por
   projetos como [UnreleasedArenaData](https://github.com/multimeric/UnreleasedArenaData)
   e [mtgatool-metadata](https://github.com/mtgatool/mtgatool-metadata). É
   tradução oficial de verdade, ao custo de depender de instalação do Arena ou
   de dump de terceiro.
3. **Tradução automática** — descartada: estraga terminologia de regra, que em
   Magic é o que mais importa.

A decisão atual é perguntar no CLI, carta a carta. A opção 2 fica como evolução
possível.

## 3. Arte

| Fonte | Dimensões medidas | Observação |
|---|---|---|
| MTGPics | 1920 x 1080 | `https://www.mtgpics.com/pics/art/{set}/{numero:03d}.jpg` |
| Scryfall `art_crop` | 626 x 457 | Padrão do Card Conjurer |
| Scryfall `png` | 745 x 1040 | Carta inteira com moldura, não serve como arte |

O `art_crop` precisa de cerca de 2x de ampliação pra preencher o box de arte de
um canvas 1500x2100, e borra. O MTGPics tem aproximadamente sete vezes mais
pixels.

A boa notícia é que **não há código a escrever**: o Card Conjurer já tenta o
MTGPics primeiro e cai pro `art_crop` quando dá 404, na função
`tryMTGPicsArt`. É a mesma estratégia do
[mtg-art-downloader](https://github.com/Investigamer/mtg-art-downloader).

## 4. Comparativo de resolução final

Por que gerar em vez de baixar a imagem pronta:

| | Scryfall PNG | Card Conjurer |
|---|---|---|
| Dimensões | 745 x 1040 | 1500 x 2100 |
| Megapixels | 0,77 | 3,15 |
| DPI em 63,5 x 88,9 mm | ~298 | ~600 |

298 DPI é o piso aceitável pra impressão; 600 é confortável.

## Referências

- [Card Objects · Scryfall API](https://scryfall.com/docs/api/cards)
- [Languages · Scryfall API](https://scryfall.com/docs/api/languages)
- [Card Imagery · Scryfall API](https://scryfall.com/docs/api/images)
- [Bulk Data Files · Scryfall API](https://scryfall.com/docs/api/bulk-data)
- [Changes to Magic Product Languages in 2024 · Wizards](https://magic.wizards.com/en/news/announcements/changes-to-magic-product-languages-in-2024)
- [Investigamer/cardconjurer](https://github.com/Investigamer/cardconjurer)
- [Investigamer/mtg-art-downloader](https://github.com/Investigamer/mtg-art-downloader)
- [Investigamer/Proxyshop](https://github.com/Investigamer/Proxyshop)
- [Reviewed: The Best Custom MTG Card Sites & Apps · Draftsim](https://draftsim.com/mtg-card-maker/)
