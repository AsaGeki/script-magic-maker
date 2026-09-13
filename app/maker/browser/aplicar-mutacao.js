// A moldura de mutacao tem duas caixas de texto: a de cima leva a linha da
// mutacao, com o custo e o lembrete, e a de baixo o resto das regras. O import
// do gerador escreve tudo junto na caixa de regras, entao a separacao sai daqui.
//
// A linha da mutacao e sempre a primeira, e o Scryfall a traz inteira numa
// linha so - inclusive o lembrete entre parenteses.
() => {
    const texto = card.text.rules.text;
    const quebra = texto.indexOf('\n');
    card.text.mutate.text = quebra === -1 ? texto : texto.slice(0, quebra);
    card.text.rules.text = quebra === -1 ? '' : texto.slice(quebra + 1);
    return drawTextBuffer();
}
