// writeText() (motor de texto do proprio site) troca a ultima letra de uma
// palavra por um glifo decorativo (area de uso privado do Unicode) quando a
// fonte do campo e exatamente 'belerenb' e a palavra termina em f/h/m/n/k.
// Esse glifo nao renderiza no Chromium que o Playwright usa - vira caixa
// vazia, mesmo a fonte tendo o glifo certo. E so floreio (nao muda a letra),
// entao registrar a MESMA fonte sob outro nome e trocar o `.font` do campo
// evita o gatilho (literal, `font.endsWith('belerenb')`).
(nomeDaFonte) => {
    Object.values(card.text).forEach((campo) => {
        if (campo.font === 'belerenb') {
            campo.font = nomeDaFonte;
        }
    });
}
