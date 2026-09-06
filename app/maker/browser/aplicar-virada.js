// A moldura de carta virada tem uma segunda metade girada 180 graus, com nome,
// tipo, regras e poder/resistencia proprios. O import do gerador trata cada
// face como uma carta separada e para na primeira, entao a metade virada
// precisa ser escrita aqui.
(args) => {
    card.text.title2.text = args.nome;
    card.text.type2.text = args.tipo;
    card.text.rules2.text = args.regras;
    card.text.pt2.text = args.pt;
    // A linha de tipo virada vai ate a borda, por baixo do poder/resistencia da
    // metade de baixo - o mesmo estreitamento que a de cima ja recebe.
    if (args.pt) {
        card.text.type2.width = 0.8292 - card.text.pt2.width - 0.02;
    }
    return drawTextBuffer();
}
