# edge/evidence_packager — o pacote de evidência

Monta, para cada evento, um arquivo único, autocontido e verificável. É o que
transforma uma detecção em algo que resiste a contestação.

## Conteúdo de cada pacote

- áudio bruto, 10 s antes e 10 s depois do pico (do buffer do `audio_capture`);
- SPL estimado pelo array, com a referência da calibração usada e a marcação
  `valor_legal: false`;
- leitura do instrumento certificado, quando presente (`modo=autuacao`);
- imagem da placa e imagem panorâmica, quando a câmera foi acionada;
- ângulo de chegada estimado e sua confiança;
- timestamp sincronizado por NTP e geolocalização fixa do nó;
- classe prevista e score do classificador, com a versão do modelo;
- versão da política de decisão que gerou o acionamento;
- modo de operação vigente no momento da captura.

## Integridade

Cada arquivo de mídia entra no manifesto com seu próprio SHA-256. O manifesto é
serializado de forma canônica (chaves ordenadas) e recebe um hash próprio.
Qualquer alteração posterior em qualquer campo ou byte de mídia muda o hash — e
a verificação falha.

A verificação não depende do nosso sistema: o pacote é um zip com um JSON
dentro, e existe um comando de verificação independente. Quem recebe o pacote
consegue conferir sozinho.

## O que **não** entra no pacote

Nenhum texto de placa. O nó não lê placa (decisão D10). A imagem vai; a
identificação do veículo, se e quando ocorrer, acontece no backend, sob a
política de retenção de `docs/legal/lgpd.md`.
