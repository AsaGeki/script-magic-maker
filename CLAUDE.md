# CLAUDE.md — script-magic-maker

Instruções específicas deste repositório. O que vale para todo projeto está no
`CLAUDE.md` global; aqui ficam só as regras que nascem deste código e as
exceções ao global.

O que o projeto é e como rodar: [README.md](README.md). Não repetir isso aqui.

## Portão de qualidade — obrigatório

`app/__init__.py` roda lint, formato e tipagem no import do pacote. **Reprovou,
a aplicação não sobe** — CLI, API e scripts, todos. Não existe variável de
ambiente para desligar.

```bash
uv run cli.py check            # roda as mesmas três verificações
uv run cli.py check --corrigir # aplica o que o ruff sabe arrumar sozinho
```

As três são `ruff check`, `ruff format --check` e `ty check`, pelo interpretador
do venv, com as versões travadas no `uv.lock`. Levam ~0,5 s com cache quente.

### Supressão de regra passa pelo dono

**Nunca escrever `# noqa` nem acrescentar regra ao `ignore` do `pyproject.toml`
por conta própria.** Cada supressão é uma decisão dele, e o pedido precisa vir
com o argumento de por que ignorar é melhor do que corrigir em código:

1. o que a regra detecta e por que ela existe;
2. o trecho exato que dispara;
3. como ficaria o código corrigido;
4. o custo e o risco de corrigir;
5. a recomendação, e o motivo.

Todo `# noqa` carrega o motivo na própria linha (`# noqa: S603 - comando fixo,
sem entrada de fora`). Motivo genérico não serve, e motivo falso é pior que
supressão nenhuma — já aconteceu de um `# noqa: PLC0415 - evita ciclo de import`
apontar para um ciclo que não existia.

Hoje há **um** ignore global (`TRY003`) e as supressões pontuais aprovadas.

## Proibições

### Nunca gerar carta por iniciativa própria

Não rodar `scripts/regerar.py`, `scripts/gerar-deck.py`, `cli.py fill` nem
qualquer coisa que chame `fill_card()` sem ele mandar, com essas palavras. Cada
carta leva ~30 s, prende a porta 4242 e ocupa a máquina por minutos; uma rodada
não pedida derruba o que ele estiver rodando.

Ao terminar uma correção que muda o desenho da carta: dizer qual comando
regenera o quê, e esperar.

### Nunca injetar JavaScript no gerador por `page.evaluate`

Defeito do Card Conjurer se corrige **no código do gerador**, não com JavaScript
em string dentro do Python. Remendo por injeção é código sem tipagem, sem lint e
sem teste, morando longe do que ele conserta.

Se a única saída for contornar por fora, dizer isso explicitamente e perguntar
antes de escrever.

### Nunca chumbar lista dentro do código

Nada de conjunto fixo de IDs, edições ou casos conferidos a olho **no caminho
automático**. Dado curado à mão envelhece sem aviso, só cobre o que alguém já
olhou e mascara a ausência de uma regra de verdade.

Quando a detecção automática não fechar: dizer isso com o dado que sustenta a
conclusão e apresentar só as opções algorítmicas — ou o "deixa como está". Ele
prefere o defeito visível a uma correção que finge ser geral. O que ainda diverge
da carta impressa mora em [PENDENCIAS.md](PENDENCIAS.md).

A saída para o caso que não fecha por regra nenhuma é o `excecoes.toml`, e ela é
**dele**: propor a entrada com o dado medido, e escrever só depois do aval.

### Nunca afirmar sem medir

Alegação sobre desempenho, sobre o que uma regra de lint detecta ou sobre o que
uma biblioteca faz vai medida ou testada antes de virar argumento. Um `-X
importtime`, um arquivo de teste no temp, um `perf_counter` — e o número vai
junto da afirmação.

## Git

Commit vai **direto na `main`**. Não criar branch de feature nem abrir PR por
conta própria — é exceção explícita ao `CLAUDE.md` global. Continua valendo:
commit só com autorização, Conventional Commits em português, e nunca se incluir
como autor ou coautor.

## Onde cada coisa mora

| Lugar | O que entra |
|---|---|
| `patches/cardconjurer/*.patch` | Correção de defeito do gerador. Numerado, com a marca `script-magic-maker: <nome>` no código alterado |
| `app/maker/browser/*.js` | Ajuste que **depende de dado da carta** (aplicar saga, moldura, nome traduzido) |
| `vendor/` | Clone do Card Conjurer, ~5 GB, fora do controle de versão. Edição direta aqui **não sobrevive** ao próximo clone |
| `app/rede.py` | O que todo módulo que fala com serviço de fora compartilha: cabeçalho, ritmo entre requisições, retentativa no 429 e validade de cache baixado. A **política de erro não mora lá** — cada chamador decide se a falha vira exceção ou log |
| `excecoes.toml` | Correção à mão de uma impressão, com o motivo obrigatório ao lado. Lida por `app/excecoes.py`, que recusa entrada sem motivo e campo que não existe |
| `output/` | Imagem gerada. Nunca versionado |
| `PENDENCIAS.md` | O que ainda diverge da carta impressa, com o dado já medido sobre cada caso |
| `DECK.md` | Formato da lista de deck |
| `MARCADORES.md` | Catálogo de marcadores físicos |

A marca nos patches é o que `app/vendor/patches.py` usa para saber se o clone
está corrigido, sem chamar o git. Patch sem marca é recusado; patch que não
aplica derruba o `setup` com erro — e é assim que tem que ser, porque seguir sem
ele geraria carta errada em silêncio.

## Fontes de dados

Precedência, e o motivo de cada uma:

1. **Scryfall** — fonte primária de todo dado de carta. A documentação dele pede
   ~100 ms entre chamadas, mas o servidor não aguenta: medindo daqui, qualquer
   intervalo até 0,35 s fecha no 20º pedido e 0,50 s passa 60 seguidos. É esse o
   `INTERVALO_ENTRE_REQUISICOES`. Depois do 429 ele fica fechado por dezenas de
   segundos e devolve a conta regressiva no `Retry-After` — encurtar a espera só
   gasta tentativa.
2. **MTGJSON** — acervo completo em SQLite (~650 MB, `vendor/mtgjson`), usado
   **só quando o Scryfall falha**. Mesma carta, mesma ordem de impressões, sem
   limite.
3. **MTG Arena** (`vendor/arena`) — tradução PT que o Scryfall não tem: carta
   pós-corte e o nome, a regra e a linha de tipo das fichas. A Wizards parou de
   imprimir em português depois de Modern Horizons 3 (`2024-06-14`), e para essa
   carta o Arena é a única fonte oficial de português que existe. Ele indexa a
   ficha pelo número da ilustração **dele**, que não é sempre o do Scryfall — a
   mesma ficha em outra arte só é achada pelo nome em inglês.
4. **MTGPics** — arte em alta resolução. O art_crop do Scryfall (626x457) é
   pequeno para uma carta gerada em 2010x2814. Ao lado da ilustração ele guarda
   papel de parede da mesma arte, com a mesma paleta e outra composição: quem
   decide é o quanto o art_crop encaixa dentro de cada uma, não o tamanho.
5. **hexproof.io** — símbolo de expansão com a cor da raridade, quando a
   biblioteca do clone não tem a edição (ela para na data do clone). O
   `svgs.scryfall.io` é o último elo e vem preto.

Nenhuma das secundárias pode derrubar quem chamou: falha nelas vira log e o
fluxo segue com o que o Scryfall trouxe.

## Detalhes que não se adivinham pelo código

- O gerador **não avisa quando terminou de desenhar**. Quem decide é
  `_esperar_desenho()`, amostrando o canvas até parar de mudar.
- Trocar de impressão à toa dispara uma segunda consulta da edição e o número do
  colecionador sai duplicado (`187/361/361`). Por isso `_selecionar_impressao()`
  devolve se precisou mesmo trocar.
- O servidor local (`app/vendor/server.py`) existe porque o Card Conjurer carrega
  molduras por XHR, que `file://` bloqueia. Ele monta cabeçalho e rodapé em volta
  dos fragmentos HTML e declara `charset=utf-8` — sem isso o acento do próprio
  código vira lixo na imagem.
- `fill_card()` devolve **uma imagem por face**: carta de duas faces sai em
  duas, na ordem em que a carta imprime, e todo o resto sai em uma.
- Campo emprestado ao `card` antes do `autoFrame()` tem que ser **lido antes do
  primeiro `await`** de quem o usa. O `autoFrame()` é síncrono e não espera as
  funções de moldura, então o `delete` logo depois dele roda antes de a função
  assíncrona voltar do primeiro `await` — o campo chega lá como `undefined`.
- O `printed_text` de carta de duas faces vem com o rodapé do outro lado colado
  no fim, e a carta impressa abrevia o rótulo: `Criatura — Elfo Druida` vira só
  `Elfo`. Quem corta e quem lê o rótulo é o mesmo par de funções em
  `app/maker/service.py`.
