# Catálogo de marcadores físicos

## Primeira leva pra produção

Do catálogo completo abaixo, o que entra primeiro: **boost assimétrico**
(+1/+1 e -1/-1 puros ficam por conta de dado colorido — verde/vermelho — já
em mãos), **marcador de característica** (voar, ímpeto e as outras
evergreen concedidas por efeito), **veneno** e **carga genérica**. O resto
do catálogo fica registrado como referência pra quando entrar em pauta.

Tudo que hoje, jogando Magic em papel, precisa de algum objeto físico além
das cartas do deck — contador, ficha ou indicador de estado — pra que os
jogadores não percam a informação da partida. Organizado por família, com a
regra do Comprehensive Rules que sustenta cada item e se já existe caminho no
pipeline atual (`fill_card`, fichas de criatura) ou se é objeto novo.

## 1. Contadores que ficam sobre uma permanente

Marcador colocado em cima de uma carta específica (criatura, artefato,
planeswalker...), some se a carta sai do campo.

| Contador | Regra | Observação |
|---|---|---|
| +1/+1 | 122, 704.5g/h | O mais comum de longe; anula par a par com -1/-1. **Resolvido por dado colorido** (verde = +X/+X), não precisa impressão |
| -1/-1 | 122, 704.5g/h | Anula par a par com +1/+1. **Resolvido por dado colorido** (vermelho = -X/-X), não precisa impressão |
| Boost assimétrico (+1/0, +1/-1, 0/-1...) | 122.1e | Poder e resistência mudam em direções diferentes — dado de cor única não cobre. Marcador impresso com os dois valores, faixa -3 a +3 por eixo (42 combinações, exclui a diagonal p=t já coberta pelo dado) |
| Lealdade (loyalty) | 121.5c, 306 | Planeswalker; hoje sai impresso na própria carta como número inicial, o jogo soma/subtrai por cima |
| Carga (charge) | 122.1e | Genérico multiuso — sagas antigas, artefatos, etc |
| Escudo (shield) | 122.3g | Anula o próximo dano/destruição que o receberia |
| Atordoamento (stun) | 122.3j | A permanente não desvira na próxima desvirada; remove um contador em vez disso |
| Idade (age) | — | Suspend usa contador de tempo (ver seção 5), não "age" isolado |
| Definhamento (fade) / Esgotamento (depletion) | 122.3 | Decrescentes, cartas antigas (Onslaught/Odyssey) |
| Munição (ammo) | 122.3a | Fica no equipamento (besta), não no jogador |
| Praga (feather/oil/etc temáticos) | 122.3 | Vários nomes cosméticos por bloco, mesma mecânica de contador genérico — visualmente todos servem de um marcador liso numerado |

### Marcador de característica (habilidade concedida)

Não é contador de regra 122 — é um lembrete físico de que a permanente
ganhou uma palavra-chave evergreen temporariamente (efeito tipo "criaturas
que você controla ganham voar até o final do turno") ou por texto impresso
difícil de lembrar de cabeça. As 12 evergreen (nome oficial em português,
conferido nas impressões traduzidas do Scryfall):

Voar, Ímpeto, Atropelar, Vigilância, Ameaça, Toque mortífero, Iniciativa
(first strike), Golpe duplo (double strike), Indestrutível, Ligação
vitalícia, Alcance, Resistência a magia (hexproof).

**Cobertura hoje:** nenhum contador de permanente é gerado pelo pipeline —
não são carta, são ficha física genérica (normalmente um pino redondo com
número ou sinal, reutilizável entre partidas). Não precisa de arte por carta,
só de um conjunto de fichas com símbolo/número.

## 2. Contadores associados ao jogador

Não ficam em cima de uma carta — ficam "do lado" do jogador, valem pro jogo
inteiro.

| Contador | Regra | Faixa típica |
|---|---|---|
| Veneno (poison) | 104.3c, 122.1e | 0 a 10 (10 = derrota) |
| Energia (energy) | 122.1e | Sem teto, soma e gasta |
| Experiência (experience) | 122.1e | Sem teto, só cresce (Commander) |
| Radiação (rad) | 122.1e | Sem teto, causa perda de vida crescente no upkeep |

**Cobertura hoje:** nenhuma. Cada jogador precisa de um marcador por tipo,
normalmente um dado ou contador de rosca ao lado do total de vida.

## 3. Indicadores de estado único na mesa

Binário ou de poucos estágios, não numérico — troca de dono/lado durante o
jogo, só existe um por mesa (ou um por jogador, mas sem contagem).

| Indicador | Regra | Comportamento |
|---|---|---|
| Dia/Noite (day/night) | 726 | Um estado pro jogo inteiro, começa "nenhum", vira dia ou noite e alterna |
| Monarca (monarch) | 723 | Um jogador por vez; passa por combate ou efeito |
| Iniciativa (initiative) | 725 | Um jogador por vez; anda com a masmorra (dungeon) |
| Bênção da cidade (city's blessing) | 702.132 | Por jogador, binário, nunca se perde depois de ganho (Ascend) |
| O Anel te tenta (the ring tempts you) | 701.52 | Por jogador, 4 estágios progressivos (Sauron, LOTR) |

**Cobertura hoje:** nenhuma. São os que mais pedem um objeto de mesa
"vistoso" (todo mundo enxerga de longe quem é o monarca, por exemplo) — o
tipo de marcador que costuma virar peça grande, não fichinha.

## 4. Vida e dano

Não é mecânica nova, é a base de qualquer partida em papel.

| Item | Regra | Observação |
|---|---|---|
| Total de vida | 119 | 20 (padrão), 40/30 (Commander/Brawl conforme variante) |
| Dano de comandante | 903.10a | Um rastreador por oponente, até 21 mata; numa mesa de 4 são 3 rastreadores por jogador |
| Imposto de comandante (commander tax) | 903.8 | Cresce 2 a cada vez que o comandante muda de zona; útil ter tracker dedicado embora não seja contador oficial de regra |

**Cobertura hoje:** nenhuma. É o marcador que todo jogador de Commander mais
sente falta de ter em quantidade suficiente (3+ rastreadores de dano por
pessoa numa mesa de 4).

## 5. Auxiliares de jogo que não são contador numérico

| Item | Regra | Pra que serve |
|---|---|---|
| Contador de tempo (suspend) | 702.61 | Decresce a cada upkeep até a carta resolver |
| Dado (d20/d6/d4) | glossário "Roll a die" | Cartas que mandam rolar dado (ex: cartas de Aventuras no Reino Esquecido, algumas de humor) |
| Moeda | glossário "Flip a coin" | Cartas que mandam tirar cara ou coroa |
| Carta genérica em branco | 707.4a | Pra Manifest/Morph — carta virada de bruços, precisa parecer igual a qualquer outra virada |
| Masmorra (dungeon card) | 725, 701.51 | Card físico com as salas, joga-se a ficha de iniciativa em cima avançando sala a sala |
| Roda de Attraction | 715 (Un-sets) | Nicho, só em produtos "Un" |

**Cobertura hoje:** nenhuma — são objetos de mesa auxiliares, fora do
conceito de "carta preenchida".

## 6. Fichas com nome e texto (já são "carta" no sentido do Scryfall)

Diferente das seções 1-5, estas têm nome, tipo e texto de regras próprios —
já cabem no pipeline de carta hoje, via [`app/cards/fichas.py`](app/cards/fichas.py)
e a busca de token no Scryfall. Não é escopo novo, só reforçando o que já
está coberto:

- Fichas de criatura geradas por outras cartas (Soldado 1/1, Zumbi 2/2...)
- Fichas de artefato com regra própria: Clue (Pista), Food (Comida),
  Treasure (Tesouro), Powerstone, Blood (Sangue), Map (Mapa), Gold (Ouro),
  Incubator, Junk
- Role token (Aura anexada com nome e texto — Monster, Wicked, Young Hero...)
- Emblema — [PENDENCIAS.md](PENDENCIAS.md) já registra que cai na moldura de
  criatura comum hoje

## Resumo do que falta pra imprimir

Comparado ao que o script já gera (cartas e fichas-carta), o que fica de
fora e precisaria de peça nova de design são as seções 1 a 5: contadores
genéricos numerados (+1/+1, veneno, energia...), indicadores de estado
(monarca, dia/noite, iniciativa...), trackers de vida/dano e os auxiliares
não numéricos (dado, moeda, carta em branco, masmorra).
