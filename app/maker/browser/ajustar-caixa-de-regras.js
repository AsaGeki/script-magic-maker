// A caixa de regras das molduras de criatura desce por tras da caixa de
// poder/resistencia. O gerador encolhe a fonte ate o texto caber na ALTURA da
// caixa, entao texto longo "cabe" invadindo o P/R - foi o que aconteceu com o
// Terror Tolariano, cuja ultima linha de flavor saiu por baixo do 5/5. Na carta
// oficial nada passa dali: a fonte diminui mais. Baixar o fim da caixa ate o
// topo do P/R faz o mesmo encolhimento chegar nesse resultado.
() => {
    const regras = card.text.rules;
    const pr = card.text.pt;
    if (!regras || !pr || !pr.text) { return; }
    const limite = pr.y - 0.004;
    if (regras.y + regras.height > limite) {
        regras.height = limite - regras.y;
    }
}
