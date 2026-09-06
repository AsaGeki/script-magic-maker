// A moldura de aventura reparte a metade de baixo em duas: o livro da aventura
// na esquerda, com nome, custo e tipo proprios, e as regras da criatura na
// direita. O import do gerador trata cada face como uma carta separada e para
// na primeira, entao a metade da aventura precisa ser escrita aqui.
//
// A criatura ja veio pelo import; so o texto dela muda de campo, porque na
// moldura normal ele ocupava `rules` e aqui ocupa `rules2`.
(args) => {
    card.text.rules2.text = card.text.rules.text;
    card.text.rules.text = args.regras;
    card.text.title2.text = args.nome;
    card.text.type2.text = args.tipo;
    card.text.mana2.text = args.custo;
    // O nome e o custo da aventura dividem a mesma caixa, com o custo alinhado a
    // direita: sem estreitar o nome, os dois se sobrepoem. O simbolo e quadrado
    // e tem a altura da fonte (60/2100), que em largura de carta da 0.052.
    const simbolos = (args.custo.match(/{[^}]+}/g) || []).length;
    card.text.title2.width = 0.4 - simbolos * 0.052;
    return drawTextBuffer();
}
