// processScryfallCard() faz `type_line = printed_type_line` e `oracle_text =
// printed_text` sem fallback pro ingles, e importCard() so cria <option> com
// type_line verdadeiro: impressao pt parcial some do dropdown ou sai com a
// caixa de texto vazia. As duas sao remendadas aqui.
//
// A traducao do Arena entra aqui, e nao depois: fetchScryfallData ja rodou o
// processScryfallCard(), entao estes sao os campos finais que changeCardIndex()
// le, e o proprio site aplica curly quotes, italico de lembrete e formatacao de
// flavor uma vez so.
(args) => {
    const { nome, idAlvo, tipoDeReserva, textoDeReserva, tipoTraduzido, textoTraduzido, arenaId, arenaTexto, arenaFlavor, palavrasDeHabilidade } = args;
    // Lista do MTGJSON (ver app.cards.palavras_chave): diz quais palavras antes
    // do travessao saem em italico. Sem ela o changeCardIndex usa a embutida.
    window.palavrasDeHabilidade = palavrasDeHabilidade || [];
    fetchScryfallData(nome, (cards) => {
        cards.forEach((c) => {
            if (!c.type_line || c.type_line === 'Card') {
                c.type_line = tipoDeReserva;
            }
            if (!c.oracle_text) {
                c.oracle_text = textoDeReserva;
            }
            // Traducao montada fora do Scryfall: a linha de tipo das fichas
            // (app.cards.fichas) e o texto vazio do terreno basico.
            if (c.id === idAlvo) {
                if (tipoTraduzido) c.type_line = tipoTraduzido;
                if (textoTraduzido !== null) c.oracle_text = textoTraduzido;
            }
            // O nome fica de fora: importCard() usa c.name pra buscar a arte, e
            // traduzido a busca volta vazia (ver _aplicar_nome_traduzido).
            if (arenaId && c.id === arenaId) {
                if (arenaTexto) c.oracle_text = arenaTexto;
                if (arenaFlavor) c.flavor_text = arenaFlavor;
            }
        });
        // importCard() desenha a impressao do indice 0 sozinho: pondo a nossa na
        // frente ele acerta de primeira, sem uma composicao inteira jogada fora.
        const indiceAlvo = cards.findIndex((c) => c.id === idAlvo);
        if (indiceAlvo > 0) {
            const [alvo] = cards.splice(indiceAlvo, 1);
            cards.unshift(alvo);
        }
        importCard(cards);
    }, 'prints');
}
