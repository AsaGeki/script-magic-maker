// Titulo e custo de mana ficam em caixas separadas e o gerador nao encolhe uma
// por causa da outra. Encurtar a do titulo ate onde o custo comeca faz o
// writeText() reduzir a fonte ate caber.
//
// A conta do avanco por simbolo e a do writeText(): largura 0.78 do corpo da
// fonte, mais o espacamento dos dois lados.
() => {
    const titulo = card.text.title;
    const mana = card.text.mana;
    if (!titulo || !mana || !mana.text) { return; }
    const simbolos = (mana.text.match(/{[^}]*}/g) || []).length;
    if (!simbolos) { return; }

    const corpo = card.height * (mana.size || 0.038);
    const espacamento = corpo * 0.04 + card.width * (mana.manaSpacing || 0);
    const larguraDoCusto = simbolos * (corpo * 0.78 + espacamento * 2);
    const inicioDoCusto = card.width * ((mana.x || 0) + mana.width) - larguraDoCusto;
    const folga = card.width * 0.012;
    const fimDoTitulo = card.width * (titulo.x + titulo.width);
    if (fimDoTitulo > inicioDoCusto - folga) {
        titulo.width = (inicioDoCusto - folga) / card.width - titulo.x;
    }
}
