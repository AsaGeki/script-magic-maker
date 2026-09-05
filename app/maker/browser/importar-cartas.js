// importCard() do proprio site so cria <option> quando card.type_line e
// verdadeiro - e processScryfallCard() faz `card.type_line = card.printed_type_line`
// e `card.oracle_text = card.printed_text`, os dois sem fallback nenhum pro
// ingles. Quando o Scryfall tem uma impressao pt parcial (nome traduzido,
// type_line/oracle_text ainda null - o mesmo problema de dado incompleto
// documentado em app.cards.models), a carta some do dropdown em silencio e
// trava o resto do fluxo (type_line vazio) ou sai com a caixa de texto em
// branco (oracle_text vazio) - os dois corrigidos aqui do mesmo jeito.
//
// Tambem e aqui, e nao depois via override, que a traducao do Arena entra
// (quando pedida): fetchScryfallData ja roda processScryfallCard() antes de
// chamar este callback, entao name/oracle_text/flavor_text aqui sao os campos
// FINAIS que changeCardIndex() vai ler. Patchar antes de importCard() faz o
// proprio site aplicar curlyQuotes, itailico de reminder text e formatacao de
// flavor uma vez so - a mesma coisa que ele faz pra carta com pt de verdade.
(args) => {
    const { nome, idAlvo, tipoDeReserva, textoDeReserva, tipoTraduzido, textoTraduzido, arenaId, arenaNome, arenaTexto, arenaFlavor, palavrasDeHabilidade } = args;
    // Lista oficial do MTGJSON (ver app.cards.palavras_chave): e ela que diz
    // quais palavras antes do travessao saem em italico. O changeCardIndex
    // le daqui; sem ela ele cai na lista embutida do proprio gerador.
    window.palavrasDeHabilidade = palavrasDeHabilidade || [];
    fetchScryfallData(nome, (cards) => {
        cards.forEach((c) => {
            if (!c.type_line || c.type_line === 'Card') {
                c.type_line = tipoDeReserva;
            }
            if (!c.oracle_text) {
                c.oracle_text = textoDeReserva;
            }
            // Traducao montada fora do Scryfall, que o processScryfallCard()
            // do proprio site nao tem como aplicar sozinho numa impressao em
            // ingles: a linha de tipo das fichas (app.cards.fichas) e o texto
            // vazio do terreno basico (ver _texto_traduzido). O nome nao entra
            // aqui - ver _aplicar_nome_traduzido.
            if (c.id === idAlvo) {
                if (tipoTraduzido) c.type_line = tipoTraduzido;
                if (textoTraduzido !== null) c.oracle_text = textoTraduzido;
            }
            if (arenaId && c.id === arenaId) {
                c.name = arenaNome;
                if (arenaTexto) c.oracle_text = arenaTexto;
                if (arenaFlavor) c.flavor_text = arenaFlavor;
            }
        });
        // importCard() desenha a impressao do indice 0 sozinho. Colocando a
        // impressao que queremos ja na frente, ele acerta de primeira - sem
        // isso, desenhava a errada e so depois _selecionar_impressao() (Python)
        // trocava e desenhava tudo de novo, dobrando o tempo de composicao das
        // camadas.
        const indiceAlvo = cards.findIndex((c) => c.id === idAlvo);
        if (indiceAlvo > 0) {
            const [alvo] = cards.splice(indiceAlvo, 1);
            cards.unshift(alvo);
        }
        importCard(cards);
    }, 'prints');
}
