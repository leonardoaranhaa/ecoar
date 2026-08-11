# vision/vehicle_type — confirmação de tipo de veículo

Antes de aceitar uma captura como válida, um classificador de imagem confirma
que o veículo no quadro é de fato uma motocicleta. Evita que um carro passando
no mesmo instante seja associado ao evento sonoro.

Modelo pré-treinado leve com ajuste fino (linha MobileNet), não treino do zero.

Saída: tipo previsto + score. Divergência entre o que o áudio indica e o que a
imagem mostra **não** descarta o evento em silêncio — marca como ambíguo para
revisão humana.
