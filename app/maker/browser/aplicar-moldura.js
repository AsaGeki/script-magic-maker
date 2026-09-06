// autoFrame() e cardFrameProperties() decidem a moldura procurando "Land",
// "Artifact", "Vehicle", "Creature" e "Add" na linha de tipo e no texto de
// regras, literais em ingles - nada disso bate com a carta em portugues.
// Emprestar os dois campos em ingles durante a chamada resolve todas de uma vez.
//
// Devolver logo depois e seguro: as funcoes de moldura recebem o texto por
// argumento e ja leram o valor. E escrever em card.text[...].text direto, sem
// passar pela caixa de texto da interface, nao dispara textEdited() - que
// agendaria outro autoFrame() 500ms depois, com o portugues de volta.
//
// A moldura de terreno de arte cheia nao tem caixa de regras, e e do texto dela
// que sai a cor do terreno: sem o campo, ele e criado so durante a chamada.
//
// O custo de mana entra pelo mesmo caminho: a cor da moldura sai dele, e ficha
// nao tem custo nenhum - a Fada azul cairia na moldura de artefato.
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
    const devolverCusto = emprestar('mana', args.custoDeCor);
    // A moldura dividida precisa da cor das DUAS metades, e so a da frente cabe
    // no campo de custo.
    card.coresDaOutra = args.coresDaOutraMetade;
    autoFrame();
    delete card.coresDaOutra;
    devolverCusto();
    devolverRegras();
    devolverTipo();
}
