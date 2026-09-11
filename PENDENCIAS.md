# Pendências

O que ainda diverge da carta impressa, com o que já foi medido sobre cada
coisa. Fechado sai daqui; o que não tem dado de onde sair fica registrado no
fim, pra não ser investigado de novo.

## Com dado pra resolver

### Arte enquadrada errada na carta sem borda

`Golpe Relampejante (SLD 724)` sai com a arte fechada no canto superior
esquerdo: o bárbaro fica atrás da caixa de texto e sobra pedra vermelha.
Confirmado ao vivo, não é imagem velha em disco. A arte do MTGPics é a pintura
inteira (1242x1629, proporção 0,762) e a janela da carta sem borda é a carta
toda (0,714), então o corte deveria ser de 6%. A semelhança de cor com o scan
oficial dá 0,48, contra 0,79 do pior dos outros vinte e dois cards do deck.

### Arte um pouco mais fechada que a impressa

`Raptor Maxilácero (LCC 253)` perde a cachoeira da esquerda. A arte do MTGPics
é 4018x3006 (proporção 1,34) e a janela pede 1,50, então o `autoFitArt`
preenche pela largura e corta as laterais. A folga de `FOLGA_DE_ASPECTO` (0,25)
deixa passar: a distância dá 0,116 contra 0,091 do `art_crop`.

### Símbolo de coleção na moldura dividida

As duas metades saem sem símbolo. O `packSplit.js` estaciona ele fora da tela
de propósito (`setSymbolBounds {x: 2, y: 2}`) e o upstream avisa que não sabe
girar símbolo. O desenho fica em `drawCard`, que hoje desenha um símbolo só,
sem rotação: caberia desenhar dois, girados -90 graus, nas duas faixas de tipo.

### Lembrete de regra na ficha

A ficha `Dinossauro (TLCC 10)` imprime só "Trample"; a nossa escreve
"Atropelar (Esta criatura pode causar seu dano de combate excedente...)". O
lembrete vem do `oracle_text` do Scryfall, que sempre traz, e não há campo que
diga se aquela ficha imprime ou não. Ficha antiga costuma imprimir; ficha
recente de palavra-chave perene, não.

### Molduras que ainda não existem

- **Planeswalker.** O pacote existe (`packPlaneswalker*`); falta partir as
  habilidades de lealdade em blocos. Hoje o `fill_card` recusa a carta.
- **Seis layouts de duas faces** (`transform`, `modal_dfc`, `meld`,
  `reversible_card`, `double_faced_token`, `art_series`). Cada um rende duas
  imagens e o `fill_card` devolve um caminho só: é mudança de forma do
  pipeline, não moldura.
- **`leveler`, `planar`, `scheme`.** Renderizam inteiras na moldura normal; só
  falta fidelidade. Os pacotes existem.
- **Emblema.** Cai na moldura de criatura comum, como a ficha caía antes. O
  pacote é o `Emblem`, no mesmo grupo `Token-2`.

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

## Sem fonte de dado

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

## Decisões que valem revisar

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
