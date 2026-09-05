// autoFrame() e cardFrameProperties() (do proprio gerador) decidem a moldura
// procurando "Land", "Artifact", "Vehicle", "Creature" e "Add" DENTRO da linha
// de tipo e do texto de regras, tudo literal em ingles. Com a carta em
// portugues nenhuma dessas comparacoes bate: terreno vira moldura de artefato,
// veiculo perde a caixa de P/R propria, e a cor do terreno (que sai do "Add"
// do texto) nunca e encontrada. Emprestar a linha de tipo e o texto em ingles
// so durante a chamada resolve todas de uma vez, sem tocar em vendor/.
//
// Restaurar logo depois e seguro porque as funcoes de moldura recebem o texto
// por argumento - o valor ja foi lido quando esta linha roda. E escrever em
// card.text[...].text direto (em vez de passar pela caixa de texto da
// interface) nao dispara textEdited(), que agendaria um autoFrame() novo, com
// o portugues de volta, 500ms depois.
//
// A moldura de terreno de arte cheia nao tem caixa de regras, entao card.text
// chega aqui sem o campo `rules` - que e justamente de onde o autoFrame tira a
// cor do terreno. Criar o campo so pela duracao da chamada cobre isso.
(args) => {
    const emprestar = (campo, valorIngles) => {
        const original = card.text[campo];
        if (original) {
            const anterior = original.text;
            original.text = valorIngles;
            return () => { original.text = anterior; };
        }
        card.text[campo] = {text: valorIngles};
        return () => { delete card.text[campo]; };
    };

    const devolverTipo = emprestar('type', args.tipoIngles);
    const devolverRegras = emprestar('rules', args.regrasIngles);
    autoFrame();
    devolverRegras();
    devolverTipo();
}
