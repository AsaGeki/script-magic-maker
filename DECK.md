# Formato da lista de deck (`deck.txt`)

Arquivo de texto simples, 1 carta por linha. Aceita `.txt`, `.dec`, ou qualquer
exportação do [Moxfield](https://moxfield.com), [Archidekt](https://archidekt.com)
ou MTG Arena sem editar nada.

## Sintaxe de uma linha

```
<quantidade> <nome> [(EDICAO) NUMERO]
```

- **Quantidade**: `4`, `4x` ou omitida (vale 1).
- **Nome**: em português ou inglês.
- **Edição + número** (opcional): entre parênteses o código da edição (3-4
  letras) seguido do número do colecionador. Quando presente, busca **essa
  impressão exata** — sem isso, a próxima seção explica o que acontece.

Exemplos válidos:

```
4 Lightning Bolt
4x Raio
1 Kona, Rescue Beastie (DSK) 187
Sol Ring
```

## Sem edição/número: qual impressão vem?

Quando a linha não trava a edição, o script busca todas as impressões em
português daquele nome e usa **a primeira que a API do Scryfall devolver**.

Isso importa pouco pra a maioria das cartas (1 impressão só, ou pouca
diferença entre elas), mas pesa em **terreno básico e cartas com muitas
variantes** (arte alternativa, showcase, borderless, promo) — a impressão que
sai pode não ser a que você queria.

Por isso, ao importar a lista, o menu mostra as cartas que ficaram sem edição
e deixa marcar em quais você quer escolher. Cada carta marcada abre a grade
com a arte das impressões pra comparar antes de decidir; as não marcadas
seguem no automático. Terreno básico passa de 280 impressões, então a grade
desenha a arte das 12 primeiras e a lista de escolha traz todas.

**A escolha é gravada de volta no arquivo**, virando `(EDICAO) NUMERO` na
linha. Da próxima vez a carta já vem travada e não é mais perguntada.
Comentário, linha em branco, cabeçalho de seção e linha que já estava travada
não são tocados; carta repetida em mais de uma linha trava todas de uma vez.

Pra travar na mão em vez de escolher pelo menu: procure a carta no
[Scryfall](https://scryfall.com), a URL da impressão traz o código e o número
(ex: `scryfall.com/card/znr/264/...` → `(ZNR) 264`).

> Deck pré-construído (`Buscar por estrutural`) também deixa escolher, mas não
> grava nada — a lista vem do MTGJSON, não de um arquivo seu.

## Cópias divididas entre variantes

Cada combinação de nome+edição+número conta como carta separada — então pra
misturar variantes da mesma carta num deck só, usa 1 linha por variante:

```
2 Planície (ZNR) 264
3 Planície (ZNR) 265
```

Isso gera 2 imagens diferentes, com 2 e 3 cópias respectivamente na folha de
impressão.

## Seções

Linha que só tem um cabeçalho de seção (com ou sem `#`/`//` na frente) marca
o que vem depois dela:

| Cabeçalho aceito | Vira |
|---|---|
| `Deck`, `Main`, `Maindeck`, `Mainboard` | Principal |
| `Sideboard`, `Side`, `Companion` | Sideboard |
| `Commander`, `Comandante` | Comandante |

```
Commander
1 Atraxa, Praetors' Voice

Deck
1 Sol Ring
1 Arcane Signet
...

Sideboard
2 Negate
```

Linha em branco é ignorada. `#` ou `//` que não bate com nenhum cabeçalho
vira comentário puro, ignorado.
