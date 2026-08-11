# edge/audio_capture — captura de áudio

Ponto de entrada de todo o sistema. Mantém sempre os últimos 30 segundos de
áudio dos 4 microfones em memória, para que, quando um pico de som acontece, o
sistema consiga recuperar o que veio **antes** do pico — e não só depois.

## Responsabilidades

1. Capturar áudio simultâneo dos 4 microfones MEMS I2S (ICS-43434), com
   timestamps sincronizados entre canais.
2. Manter buffer circular de 30 s.
3. Calcular SPL aproximado em tempo real a partir do array.
4. Ler o instrumento de medição certificado através de uma camada de adaptação
   isolada.
5. Expor uma interface simples para `localization` e `classifier` consumirem.

## Distinção que não pode ser perdida

O array MEMS **não é** a fonte da medição oficial de dB para fins legais. O SPL
calculado a partir dele é estimativa relativa, calibrada por campanha, e serve
para acionar o classificador e a localização — nada além disso. Todo valor que
sai daqui carrega `valor_legal: false`.

A medição com validade legal vem de um instrumento certificado IEC 61672
(estação de monitoramento permanente, NMT), integrado por dados, e só é
necessária em `modo=autuacao`. Ver `docs/legal/inmetro.md`.

## Camada de adaptação do instrumento

A leitura do instrumento fica atrás da interface `SonometroReader`. Trocar de
modelo (Classe 2 na validação → Classe 1 na produção) altera **apenas** uma
classe deste módulo. Nenhum outro módulo do ECOAR conhece o protocolo do
fabricante — cada um define baud rate, comando e formato de resposta próprios.
