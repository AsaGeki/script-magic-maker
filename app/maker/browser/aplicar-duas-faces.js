// A carta de duas faces imprime, em cada lado, uma pista do outro: a
// transformada poe o poder/resistencia do verso na beirada da caixa de regras,
// e a modal poe a linha de tipo e o custo do outro lado na faixa de baixo.
//
// O import do gerador trata cada face como uma carta separada, entao nenhum
// desses campos vem preenchido - eles so existem na moldura, e so quem ja sabe
// as duas faces pode escrever neles.
(args) => {
    // A saga que transforma tem campo proprio pro poder/resistencia do verso: o
    // reminder dela e o lembrete do marcador de conhecimento, e escrever ali
    // apagaria o lembrete.
    const campoDoPT = card.text.backPT || card.text.reminder;
    if (campoDoPT) {
        campoDoPT.text = args.ptDoOutroLado;
    }
    if (card.text.flipsideType) {
        card.text.flipsideType.text = args.tipoDoOutroLado;
    }
    if (card.text.flipSideReminder) {
        card.text.flipSideReminder.text = args.custoDoOutroLado;
    }
    return drawTextBuffer();
}
