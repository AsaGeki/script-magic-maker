# Card Conjurer — notas técnicas

Referência de como o gerador funciona por dentro, pra quem for implementar o
`app/maker/`. Levantado por leitura do código-fonte do fork em 27/08/2026.

Tudo marcado como **verificado** foi conferido no código ou medido. O que está
como **a validar** é desenho proposto que ainda não foi executado.

## Qual repositório

[Investigamer/cardconjurer](https://github.com/Investigamer/cardconjurer),
branch `master`. As outras branches são `legacy-mrteferi` e `legacy-vanilla`.

Não confundir com o **cardconjurer.com** de hoje: o site oficial foi reescrito
em Angular e virou editor de template genérico, com conta e assinatura, sem o
import do Scryfall. É a versão legada preservada no fork que interessa.

## Servir localmente

O aplicativo é estático puro — o `app.conf` do repositório é um nginx que só
serve arquivo e faz `try_files`. Não há backend.

O `Makefile` oferece o caminho com Docker:

```bash
make start
# docker build -f Dockerfile --target prod . -t cardconjurer-client
# docker run -dit -h 127.0.0.1 -p 4242:4242 cardconjurer-client
```

Mas como não existe nada dinâmico, qualquer servidor estático resolve:

```bash
python -m http.server 4242
```

Docker é opcional. O projeto vai pelo servidor estático, que é uma dependência
a menos.

**Não funciona por `file://`.** O aplicativo carrega molduras e dados por XHR,
que o protocolo de arquivo bloqueia. Precisa de HTTP.

O `.env` do repositório contém uma linha só, `config.hosts << "img.scryfall.com"`,
que é configuração do host original — irrelevante rodando local.

## Peso

O repositório completo tem **2,7 GB**:

| Pasta | Arquivos | Tamanho |
|---|---|---|
| `img/frames` | 7.233 | 1.980 MB |
| `img/setSymbols` | 1.874 | 9,5 MB |
| `img/manaSymbols` | 545 | 4,6 MB |
| `data/` | 826 | — |
| `js/` | 303 | — |
| `fonts/` | 41 | — |

Dentro de `img/frames`, as maiores famílias são `m15` (2.217 arquivos, 567 MB),
`custom` (671, 186 MB) e `saga` (152, 67 MB).

Clone parcial é viável se o espaço apertar: usando só a família M15, bastam
`img/frames/m15` + `img/setSymbols` + `img/manaSymbols`, cerca de **580 MB**. O
custo é ficar preso a uma família de moldura.

## Anatomia

O motor de layout inteiro está em `js/creator-23.js` (~205 KB): quebra de
linha, substituição de símbolo de mana, itálico do flavor, escala de fonte e
composição das camadas de moldura. O formulário está em `creator/index.html`
(~54 KB).

### Funções globais relevantes

Todas no escopo global, chamáveis por `page.evaluate()`.

| Função | O que faz |
|---|---|
| `fetchScryfallData(nome, callback, unique)` | Busca no Scryfall usando o idioma do `#import-language`; chama o callback com a lista de resultados |
| `processScryfallCard(card, saida)` | Normaliza o retorno; **troca `name`, `type_line` e `oracle_text` pelos `printed_*` quando `lang != 'en'`** |
| `importCard(lista)` | Popula o seletor `#import-index` com os resultados |
| `changeCardIndex()` | Aplica a carta selecionada ao canvas: título, custo, tipo, regras, poder/resistência |
| `fetchScryfallCardByID(id, callback)` | Busca uma carta específica pelo identificador do Scryfall |
| `setAutoFrame()` | Aplica a moldura automática escolhida |
| `downloadCard(alt, jpeg)` | Gera o arquivo a partir do canvas |

### Identificadores do formulário

| Seletor | Tipo | Papel |
|---|---|---|
| `#import-name` | `input[text]` | Nome da carta a importar; dispara `importChanged()` |
| `#import-language` | `select` | Idioma; tem `pt` entre as opções |
| `#import-index` | `select` | Qual impressão usar; dispara `changeCardIndex()` |
| `#importAllPrints` | `checkbox` | Inclui todas as impressões como opção |
| `#autoFrame` | `select` | Moldura automática; dispara `setAutoFrame()` |
| `#info-language` | `input` | Sigla de idioma impressa no rodapé da carta |
| `#downloadJpg` | `h5` | Baixa como JPEG |
| `#downloadAlt` | `h5` | Abre a imagem numa aba, em vez de baixar |

O botão principal de download não tem identificador — é um
`<h3 class='download padding' onclick='downloadCard();'>`.

### Idiomas disponíveis no `#import-language`

`en`, `es`, `fr`, `de`, `it`, **`pt`**, `ja`, `ko`, `ru`, `zhs`, `zht`, `ph`.

O `ph` (fírexiano) recebe tratamento especial: injeta `{fontphyrexian}` no
texto.

### Opções do `#autoFrame`

Regular (`M15Regular-1`), Extended Art, Extended Art com caixa de texto menor,
Universes Beyond, Etched, Borderless, Phyrexian, 8th Edition, Seventh Edition,
mais as versões refeitas (`M15RegularNew`, `FullArtNew`, `UBNew`) e as
customizadas (Circuit, M15-Eighth, M15-Eighth Universes Beyond).

`Disabled` (`false`) desliga a escolha automática.

### Resolução

`baseWidth = 1500`, com canvas de **1500x2100** na maioria das molduras e
**2010x2814** em algumas — inclusive na M15 regular, que é a medida que sai na
prática aqui (cerca de 800 DPI numa carta de 63,5 x 88,9 mm). O `#previewCanvas` do HTML é 1005x1407 e serve só de
prévia na tela — a imagem real sai do `cardCanvas`.

## Fluxo de automação

**Verificado** — é o que o `app/maker/` executa.

1. Subir o servidor estático e abrir `/creator/?mtgpics=1` no Playwright, com
   `enableImportCollectorInfo`, `enableCollectorInfo` e `autoLoadFrameVersion`
   já gravados no `localStorage` antes do carregamento.
2. Carregar um pacote de molduras: `#selectFrameGroup` como `Standard-3` e
   `#selectFramePack` como `M15Regular-1`. **Sem isso nada funciona** — a
   página abre com o objeto `card` sem `text`, e tanto `changeCardIndex()`
   quanto `autoFrame()` quebram em `Cannot read properties of undefined`.
3. Definir `#import-language`, `#autoFrame` e marcar `#importAllPrints`.
4. Chamar `fetchScryfallData(nome, importCard)` por `evaluate` e aguardar o
   `#import-index` ser populado.
5. Esperar o desenho estabilizar, e só então trocar de impressão se for o caso.
6. Trocar a arte pela do MTGPics e esperar de novo.
7. Ler `cardCanvas.toDataURL('image/png')`.

O gerador não avisa quando terminou de desenhar: arte, símbolo de expansão e
camadas de moldura chegam cada um no seu tempo. A saída é amostrar o canvas
reduzido a 32x44 e considerar pronto quando três leituras seguidas saem iguais.

Sobre o passo 7, há dois caminhos:

- **Interceptar o download.** `downloadCard()` monta um `<a download>` e clica
  nele, o que o `expect_download()` do Playwright captura.
- **Ler o canvas direto.** `downloadCard()` obtém a imagem de
  `cardCanvas.toDataURL('image/png')`. Chamar isso por `evaluate` pula o
  download inteiro, é mais rápido e não passa pela exigência de creditar o
  artista. É o caminho em uso.

O ganho de chamar função em vez de preencher campo a campo é grande: no
`script-yugioh-maker` foi preciso subir do `<label>` pro elemento pai porque o
site não associava rótulo a campo, além de calcular tamanho de fonte na mão.
Aqui nada disso é necessário.

## Pegadinhas

**O servidor precisa declarar `charset=utf-8`.** O `creator/index.html` não tem
`<meta charset>`, então o navegador cai no padrão e lê `creator-23.js` como
Latin-1. Os caracteres escritos dentro do próprio código quebram: as aspas
curvas que o `curlyQuotes()` insere no texto saem como `â€™` impresso na carta.
O texto vindo do Scryfall não sofre, porque o XHR decodifica por conta própria —
o que faz o defeito aparecer só em parte das cartas.

**O MTGPics precisa ser ligado, e passa por proxy de terceiro.** A arte grande
só é tentada quando a URL tem o parâmetro `?mtgpics` — é `params.get('mtgpics')`
que libera o caminho dentro de `changeArtIndex()`. E, quando liberado, o
pedido não vai direto ao MTGPics: vai a `https://corsproxy.io/?<url>`. O
projeto contorna os dois pontos baixando a arte por fora e entregando ao
gerador como data URL via `uploadArt(src, 'autoFit')`.

**A arte não acompanha a impressão sem `#importAllPrints`.** A lista de artes
vem de uma segunda busca no Scryfall, e `artFromScryfall()` só casa a
ilustração da impressão escolhida quando essa caixa está marcada. Sem ela sai a
arte de outra edição, com o crédito de artista errado junto.

**O rodapé só aparece na segunda visita.** Se `enableCollectorInfo` não existe
no `localStorage`, o Card Conjurer grava `'true'` mas não marca a caixa — o
`checked` só é aplicado no `else`. Gravar a chave antes do carregamento resolve.

**Chamar `changeCardIndex()` duas vezes duplica o número do colecionador.**
`importCard()` já chama a função no fim; uma segunda chamada dispara outro
pedido a `/sets/{código}`, e as duas respostas concatenam o total de cartas no
mesmo campo (`187/361/361`). Esperar a primeira rodada terminar, e só trocar de
impressão quando o índice for realmente outro, evita a corrida.

**Artista é obrigatório pra baixar.** `downloadCard()` recusa e mostra
`You must credit an artist before downloading!` se o campo de artista estiver
vazio e a arte não for a imagem em branco padrão. O import do Scryfall já
preenche via `artistEdited()`, mas quem montar carta do zero precisa lembrar.

**Carta de dupla face não tem `printed_*` no topo.** Os campos traduzidos ficam
só dentro de `card_faces`. O `processScryfallCard()` já trata face por face,
mas o código do projeto que consumir o Scryfall diretamente precisa fazer o
mesmo — é o motivo do modelo `CardFace` existir.

**A arte já vem do MTGPics.** O Card Conjurer carrega
`image_uris.art_crop` e, em paralelo, tenta
`https://www.mtgpics.com/pics/art/{set}/{numero:03d}.jpg` pela função
`tryMTGPicsArt`. Como o MTGPics é 1920x1080 contra 626x457 do `art_crop`, esse
fallback é justamente o que dá qualidade — não desligar.

**Cartas do Alchemy** têm o prefixo `A-` no nome trocado por `{alchemy}` na
importação.

**Rede.** Rodando local, as molduras vêm do disco. Vale bloquear no
`page.route()` tudo que não seja `api.scryfall.com`, `cards.scryfall.io` e
`www.mtgpics.com` — acelera e deixa explícito o que sai pra internet.

## Licença

O repositório do fork não declara licença. As molduras individuais trazem aviso
próprio: o rodapé do criador menciona Creative Commons Attribution para o
template de carta. Uso pessoal e proxy caseiro, como é o caso aqui, não muda
nada — mas vale saber antes de distribuir imagem gerada.
