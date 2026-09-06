// A moldura de vanguarda tem dois campos que moldura nenhuma de carta comum
// tem: quanto a carta muda o tamanho da mao inicial e o total de vida. Sem eles
// a carta sai parecendo completa e sem o efeito dela.
(args) => {
    card.text.leftval.text = args.mao;
    card.text.rightval.text = args.vida;
    return drawTextBuffer();
}
