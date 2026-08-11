# edge/localization — de onde veio o som

Sem este módulo, o sistema só sabe que "algo bateu 80 dB". Com ele, sabe de qual
direção o som veio — que é o que permite apontar a câmera para o veículo certo e
sustentar, na evidência, que o som veio daquele veículo e não de outro na via.

## Como funciona, em linguagem simples

Um som que chega de lado atinge um microfone alguns décimos de milissegundo
antes de atingir o outro. Essa diferença minúscula de tempo é medida por
correlação cruzada entre os pares de microfones (técnica **GCC-PHAT**), e a
geometria do array converte o conjunto dessas diferenças num ângulo.

É a mesma matemática que assistentes de voz usam para saber de que lado da sala
alguém falou. Engenharia madura aplicada a um problema novo — não é
experimental.

## Saída

Ângulo de chegada (azimute, em graus) mais uma margem de confiança. A confiança
importa tanto quanto o ângulo: com dois veículos passando juntos, ou som
refletido em parede, a estimativa fica ambígua — e é melhor o sistema declarar
isso do que apontar com falsa precisão.

A geometria exata do array (raio, número de microfones, orientação) é parâmetro
de configuração, não constante de código: ela precisa bater com a montagem
física real, medida com régua.
