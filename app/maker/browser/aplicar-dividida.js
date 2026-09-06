// A moldura dividida tem duas metades completas, cada uma com nome, custo, tipo
// e regras. O import do gerador trata cada face como uma carta separada e para
// na primeira, entao a segunda metade precisa ser escrita aqui.
//
// A primeira tambem: o import escreveu a face da frente nos campos da moldura
// normal, e aqui os nomes sao outros.
(args) => {
    card.text.title.text = args.nome;
    card.text.type.text = args.tipo;
    card.text.mana.text = args.custo;
    card.text.rules.text = args.regras;
    card.text.title2.text = args.nome2;
    card.text.type2.text = args.tipo2;
    card.text.mana2.text = args.custo2;
    card.text.rules2.text = args.regras2;
    return drawTextBuffer();
}
