# Pendências

O que ainda diverge da carta impressa, com o que já foi medido sobre cada
coisa. Fechado sai daqui; o que não tem dado de onde sair fica registrado no
fim, pra não ser investigado de novo.

## Com dado pra resolver

### Arte um pouco mais fechada que a impressa

`Raptor Maxilácero (LCC 253)` perde a cachoeira da esquerda. A arte do MTGPics
é 4018x2555 (proporção 1,5726) e a janela pede 1,3670, então o `autoFitArt`
encaixa pela altura e corta 13% das laterais. A folga de `FOLGA_DE_ASPECTO`
(0,25, em log) deixa passar: a distância dá 0,140 contra 0,002 do `art_crop`.

O alinhamento pelo `art_crop` (ver `_no_enquadramento_impresso`) não alcança
este caso: o casamento acontece no sentido inverso — é a arte do MTGPics que
cabe dentro do `art_crop`, em x −0,006–1,013 e y 0,000–1,170. A arte não tem os
17% de altura que a janela pede, e qualquer posicionamento termina no mesmo
corte lateral.

Fica 13% de corte com 4018px de largura, em vez do enquadramento certo do
`art_crop` com 626px. Baixar a `FOLGA_DE_ASPECTO` trocaria um pelo outro no
acervo inteiro, e a escolha foi ficar com os pixels.

### Janela em pé com arte só do art_crop

O `art_crop` do Scryfall não é a ilustração do artista: é o recorte da imagem da
carta no tamanho da janela de arte, e o tamanho dele diz qual janela — 626x457
para a moldura comum, 745x460 para a de arte estendida, 633x468 para a de
planeswalker, 626x747 para o terreno de arte cheia. Quando a moldura escolhida
abre uma janela maior que essa, falta cena, e o `autoFitArt` amplia até cobrir.

Com arte no MTGPics isso se resolve pela projeção (ver `_pela_carta`). Sem ela
não há de onde tirar o que falta. Medindo os quatro decks, a sobreposição entre
o que o gerador mostra e o que a carta impressa mostra:

| Carta | Moldura | Sobreposição |
|---|---|---|
| `Aves do Paraíso (FIC 483)` | sem borda | 0,227 |
| `Caminho para o Exílio` sem borda | sem borda | 0,226 |
| `Impulso Aventureiro` sem borda | sem borda | 0,218 |
| `Slumbering Trudge (SOS 341)` | arte estendida | 0,693 |
| `Floresta (MH3 308)` | terreno de arte cheia | 0,645 |

São 5 das 92 imagens dos quatro decks; as outras 87 ficaram entre 0,755 e 1,000.

A saída seria pôr o `art_crop` onde a carta o põe e preencher o resto com a
própria arte esticada — na sem borda isso é 13% de faixa inventada em cima e 40%
embaixo. O `png` da carta (745x1040) tem a cena que falta, mas com o texto
impresso por cima, e a caixa de regras da moldura sem borda é transparente (o
texto sai em branco direto sobre a arte), então o texto do `png` apareceria.

### Moldura impressa dentro do art_crop que o corte não pega

O `art_crop` de carta sem borda pode trazer o nome, a linha de tipo e os filetes
impressos sobre a arte — `Aves do Paraíso (FIC 483)` vem com a faixa "Birds of
Paradise", e com o `autoFitArt` ela caía em y 0,028 da carta gerada, logo acima
da barra de título do gerador. Quem corta isso agora é `_sem_moldura_impressa`,
por duas medidas: a aresta reta que atravessa a imagem e a chapa lisa acima
dela.

O que sobra é o que passa por baixo de uma das duas. Medindo 38 `art_crop` sem
borda, 15 dos 22 com moldura impressa são cortados e nenhum dos 16 limpos é
tocado. Os 7 que escapam e o quanto cada um erra:

| Carta | Aresta | Chapa |
|---|---|---|
| `Land Tax (SLZ 247)` | 0,576 | 0,401 |
| `Birds of Paradise (SLZ 313)` | 0,910 | 0,305 |
| `Price of Progress (SLZ 307)` | 0,469 | 0,371 |
| `Smaug, Wicked Worm (HOB 245)` | 0,406 | 0,411 |
| `Chromatic Lantern (SLZ 217)` | 0,311 | 0,798 |
| `Dueling Grounds (SLZ 331)` | 0,387 | 0,831 |
| `Yargle, Glutton of Urborg (SLZ 295)` | 0,332 | 0,762 |

Baixar qualquer um dos dois limiares pega parte deles e começa a cortar arte: o
`art_crop` limpo com a maior aresta (`Ritual Sombrio, STA 26`) dá 0,533, e o de
maior chapa (`Aragorn and Arwen, Wed`, HOC 28) dá 0,393. A saída seria uma
terceira medida, não um limiar mais frouxo.

### Arte de material de origem sobre fundo chapado

`Zidane Tribal (FCA 43)` imprime o personagem sobre um fundo verde-água que faz
parte do desenho da carta; o MTGPics guarda o mesmo desenho sobre fundo branco.
A nossa sai com o fundo branco, e a moldura sem borda escreve o texto em branco
por cima. O casamento com o `art_crop` não ajuda a decidir: 63% da imagem cai
numa faixa só de cor, e por isso a confirmação por paleta é recusada (ver
`FAIXA_QUE_DOMINA`) — sem ela o recorte cortava os pés do personagem.

### Verso da moldura modal sai sem as cores da frente

Na `Clareira dos Salgueiros Ígneos (MH3 259)` o scan traz o pinline vermelho e
verde; a nossa sai no cinza de terreno. O `cardFrameProperties` recebe as cores
do lado que está sendo desenhado, e o verso é um terreno incolor — as cores da
carta estão no custo da frente, que aquele lado não vê.

### Faixa da moldura modal não cabe a habilidade de mana do verso

Na `Calca-toco (MH3 259)` o scan escreve "◀ Land  {T}: Add {R} or {G}." na faixa
de baixo; a nossa escreve só "Terreno". Preencher o `flipSideReminder` com a
habilidade resolveu metade: os dois campos partem do mesmo ponto (x 0,068,
y 0,892, largura 0,364) e o texto longo escreve por cima de "Terreno". Só uma
faixa maior no pacote, ou medir a largura do tipo antes de posicionar o segundo
campo, separaria os dois.

### Arte estendida perdida na carta de duas faces

`Sephiroth, Fabled SOLDIER (FIN 451)` tem `extendedart`, mas `_molduras_das_faces`
troca a moldura escolhida pela transformada e o acabamento se perde. O catálogo
não tem transformada de arte estendida, então hoje é uma coisa ou outra.

### Miniatura colada na ilustração do MTGPics

A ilustração de `Montanha (MH3 316)` vem com a carta inteira em espanhol colada
no canto esquerdo, e um fio dela entra na janela. O alinhamento pelo `art_crop`
não separa as duas: a miniatura mostra a mesma arte, então o casamento ali é
ambíguo por construção.

### Moldura de coleção especial

`Ragavan, Afanador Ágil (MUL 21)` sai na M15 comum; o scan tem a borda
ornamentada da Multiverse Legends. O catálogo do gerador não tem esse pacote.

### Molduras que ainda não existem

- **`reversible_card`, `double_faced_token`, `art_series`.** Saem nas duas
  imagens, mas cada lado fica na moldura escolhida para a carta: o catálogo não
  tem pacote próprio para nenhum dos três.
- **`planar`, `scheme`.** Renderizam inteiras na moldura normal; só falta
  fidelidade. O `planar` tem o pacote `Planechase`, mas a carta é em paisagem,
  fora do que a folha de impressão monta; o `scheme` não tem pacote.
- **Emblema.** Cai na moldura de criatura comum, como a ficha caía antes. O
  pacote é o `Emblem`, no mesmo grupo `Token-2`.

## Sem fonte de dado

### Símbolo genérico no canto da carta de duas faces

A transformada imprime, no canto do título, o símbolo do lado — lua e sol na
Innistrad, bússola e mapa na Ixalan, engrenagem na Kaladesh. O Scryfall não traz
campo nenhum que diga qual é, e o `frame_effects` só distingue as famílias de
moldura. As duas faces saem com o `icons/default.png` do gerador, o triângulo.

### Arte pequena no verso da carta de duas faces

O MTGPics indexa a carta, não o lado: a busca por `ref` devolve a ilustração da
frente. O verso fica no `art_crop` do Scryfall (626x457) esticado para 2010x2814,
e a diferença aparece — a textura do `Agadeem, a Subcripta` sai borrada ao lado
da frente. Só uma fonte que separe os lados resolveria.

### Verso do `meld` não existe nos dados

O `meld` é uma carta de face única no Scryfall: o verso impresso é metade da
carta que o encontro forma, e a outra metade está noutra carta. Sai a frente,
como a carta de papel a imprime; o `all_parts` aponta o resultado do encontro,
mas montar a carta grande e cortá-la em duas é outro desenho, não esta moldura.

### Barra escura no topo do terreno básico da UNF

Das 74 impressões sem borda, 20 põem o nome no topo em vez da barra de baixo:
UNF (15) e UST (5). O nome no topo já sai — `set_type` vem na própria carta e
manda as 20 para a moldura `TextlessBasicsBorderlessTopo`. A posição foi
calibrada pelo pico de borda dos scans da UNF (0,07–0,10 em três amostras) e a
saída bate: 0,08–0,09. A UST imprime um pouco mais acima (0,03–0,04) e sai um
fio baixa.

O que falta é a barra: a UNF tem uma faixa fina escura arredondada atrás do
nome, a UST não tem nada. Duas coisas travam.

A primeira é não haver como separar as duas por regra. Dentro das 20 de
`set_type` `funny`, `frame_effects` não serve — o `inverted` divide a própria
UNF (10 com, 5 sem) e ainda aparece em 29 impressões fora de `funny`. Medir a
faixa do topo nos scans também não separou: brilho médio 84,1 com `inverted`
contra 66,3 sem, com as faixas se cruzando (UNF 235 em 126,6, UST 214 em 42,1).
Sobra o código da coleção, que é lista chumbada.

A segunda é não haver asset: o catálogo do gerador não tem essa barra, então
ela teria de ser desenhada no canvas e conferida contra a carta impressa.

### Lembrete de regra na ficha

A ficha `Dinossauro (TLCC 10)` imprime só "Trample"; a nossa escreve
"Atropelar (Esta criatura pode causar seu dano de combate excedente...)". O
lembrete vem do `oracle_text` do Scryfall, que sempre traz, e não há campo que
diga se aquela ficha imprime ou não. O MTGJSON tem a coluna `originalText` na
tabela `tokens`, que seria exatamente isso, mas ela está preenchida em 23 das
9073 fichas — e `printedType`, em 3. Ficha antiga costuma imprimir o lembrete;
ficha recente de palavra-chave perene, não.

### Caixa de habilidades do planeswalker mais baixa que a impressa

O pacote fixa a linha de tipo em `0.5625` e o topo da coluna de habilidades em
`0.6239`, e a carta impressa varia isso por edição: na M20 127 a caixa do
gerador fica visivelmente mais baixa que a do scan, na WAR 150 e na M21 280 as
duas batem. Medir a faixa pela coluna central não separou os casos — a arte
clara de `Basri Ket` e de `Arlinn` é lida como se fosse a barra de tipo. A
posição vem da imagem da moldura, não de campo que dê pra deslocar, e o
catálogo tem um conjunto só.

### Linha de mutação sem a palavra "Mutação"

`Glowstone Recluse` é a única das 34 impressões de mutação em português cujo
`printed_text` começa direto no custo (`{3}{G} (Se você conjurar...`), sem a
palavra. A carta sai com a caixa da mutação assim, como o campo veio. O
`oracle_text` em inglês traz `Mutate {3}{G}`, mas montar a palavra a partir
dele pediria a tradução dela, que só existe no texto das outras 33.

### `Carnossauro Trompetista` (LCI 171)

O `printed_name` e o `printed_text` da impressão em português dizem
"Carnossauro Trompetista". O scan da mesma impressão, publicado pelo próprio
Scryfall, diz "Carnossauro Rugidor" — no título e nas duas menções dentro do
texto de regras. Seguimos o campo. Sem OCR não há de onde tirar o certo.

### Ficha `Copy`

As 39 impressões são todas em inglês, então o nome sai "Copy". O texto também
diverge: o `oracle_text` traz "(This token can be used to represent a token
that's a copy of a permanent.)" e a carta impressa diz "This token can be used
to represent a copy of something else." — outro texto, e sem parênteses.

### Total da coleção no rodapé

`Floresta (JMP 73)` imprime "073/078"; a nossa sai só com "073". O Scryfall não
traz `printed_size` para JMP e o `card_count` da coleção é 497: o 078 é a
numeração dentro do subconjunto de terrenos e não existe em campo nenhum. O
mesmo `printed_size` falta em outras 13 coleções.

### Terreno básico da ONE em fenício

As cinco impressões sem borda da ONE (365-369) só existem em fenício
(`lang: ph`): o nome é um glifo desenhado, não texto, e não há versão em
nenhuma outra língua. Não são alcançáveis por um deck em português.

### Degradê híbrido e arte da moldura dividida

O degradê já corre no eixo certo e troca de cor a 0,44 da metade, medido na MKM
248. O que sobra é a saturação das imagens `r.png`/`u.png` do catálogo, mais
forte que a da carta impressa — vale para toda moldura M15, não só para a
dividida.

A arte da dividida é mole por limite de fonte: o `art_crop` traz as duas
metades juntas em 808x280, então cada uma sai de 404x280 esticada pra 1088x744.
O MTGPics tem 1200x900, mas só de uma das duas metades, e com outro
enquadramento.

### Selo holográfico dentro da arte

Algumas impressões trazem o selo dentro da janela de arte. Medindo a razão
entre o canto e a média, as com selo deram 1,45 e 1,04 e as sem deram 1,42,
2,04, 1,19 e 1,41: as faixas se cruzam, e um detector com esse sinal cortaria
arte limpa.

### Logo no topo do papel de parede do MTGPics

O `_sem_carimbo` corta o rodapé, e é lá que mora o crédito. O bloco de logo
("MAGIC THE GATHERING | FINAL FANTASY") fica no **topo**, e a mesma medida não
separa lá: no bloco de bordas das primeiras 12% de altura, o pico do terço da
ponta deu 5,42 em `Vivi Ornitier (FIN 248)` e 6,00 em `Chocobo Viajante (FIN
406)`, os dois carimbados, contra 2,78 na arte limpa de `Wrenn e Seis` e 2,60
no símbolo de planeswalker da art series da MH2 — que é carimbo. Os dois grupos
se cruzam, e cortar 20% do topo é o tamanho que o bloco pede.

Na `Vivi Ornitier` o alinhamento pelo `art_crop` já tira quase tudo (a região
casa em x 0,116–0,850 e y 0,149–0,928, e o bloco vai até x 0,97 e y 0,20):
sobra a fatia "FINA" no canto. Na `Chocobo Viajante` o logo cai atrás da barra
de título e não aparece.

### Símbolo de planeswalker na arte de art series

`Floresta Tropical Nebulosa (MH2 250)`: o MTGPics tem duas versões da mesma
pintura — `zen/220` limpa em 640x468 e `zen/220_1` em 4000x3000, que é o scan
da art series, com o símbolo de planeswalker num canto de cima, o símbolo da
coleção no outro e o crédito no rodapé. O rodapé sai no corte; os dois de cima
ficam.

Hoje ganha a maior, e é a carimbada. O casamento com o `art_crop` prefere a
limpa (erro 15,75 contra 19,60), mas ela tem 640x468 — praticamente o tamanho
do próprio `art_crop` (626x457). É trocar dois símbolos pequenos por 4000px de
largura.

### Lembrete da palavra-chave nova quando a fonte é o Arena

`Limite Especial de Tifa (FIN 207)` imprime "Níveis (Escolha um custo
adicional.)"; a nossa sai só "Níveis". O Arena guarda a habilidade sem lembrete
nenhum, nos dois idiomas — `Tiered \n•Somersault — ...` no `en` e `Níveis
\n•Chute Mortal — ...` no `pt` — e FIN não tem impressão em português de onde
emprestar. O texto da carta é tudo ou nada: costurar o lembrete do inglês no
meio do português misturaria as duas línguas.

### História em inglês quando a irmã em português traz outra

`Bravura da Antiga Krosa (2X2 153)`: 2X2 não tem impressão em português
(`/pt` devolve 400 nas três cartas do deck), e as duas irmãs em português — TSP
204 e TSR 217 — imprimem outra história, não a tradução da que a 2X2 traz. A
comparação de texto recusa o empréstimo, e a história sai em inglês. É o
comportamento certo: a alternativa seria imprimir uma frase que não é a da
carta.

## Decisões que valem revisar

### Texto do Arena é tudo ou nada

`_reconstruir_regras` descarta a carta inteira quando UMA linha ainda está em
inglês. O acervo do Arena é traduzido por linha, e a metade dele não saiu:
9199 das 21131 habilidades do `pt-database.json` são idênticas às do `en`. Na
FIN, das 434 impressões que o Arena tem, 182 vêm com o texto todo em português,
237 com alguma linha em inglês e 15 sem habilidade nenhuma.

Não é cache velho: o release v238 (2026-09-09) é o mais novo e não traduziu
nenhuma linha a mais que o anterior — 0 mudaram de estado, e as 12 habilidades
novas trouxeram 6 já em inglês. O repositório publica um `pt-database.json` só,
sem variante.

Aproveitar as linhas traduzidas e deixar em inglês só as que faltam poria
`Lightning, Exército de Um` e `Cloud, Mercenário de Midgar` parcialmente em
português, em vez de inteiramente em inglês. O preço é a carta misturar as duas
línguas dentro da mesma caixa de texto.

### Arena contra a irmã em papel

Hoje a irmã em papel mais recente ganha, e o Arena só entra quando não há irmã
nenhuma. Numa amostra de 43 cartas da J25 que têm as duas fontes: 17 iguais, 21
com o Arena mais curto (ele traduz linha a linha, o que troca a ordem dos
parágrafos e come lembrete) e 5 com outra diferença.

O que se perde: em carta cuja única impressão em português é antiga, o texto
sai na redação daquela época. `Captivating Unicorn` fica com "entrar no campo
de batalha sob seu controle" (THB, 2020) em vez do "entrar" curto que o Arena
já usa. Um corte por data da irmã resolveria, mas não há data com fonte — a
mudança de gabarito que separa os dois casos é de 2024, depois do fim das
impressões em português.
