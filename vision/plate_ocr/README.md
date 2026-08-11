# vision/plate_ocr — leitura de placa

Dois pipelines de OCR independentes rodam sobre a mesma imagem. A leitura só é
aceita como confiável quando **ambos concordam**. Divergência vira revisão
humana, nunca escolha automática de um dos dois.

O motivo é direto: um erro de um caractere gera evidência contra o veículo
errado.

**Desligado em `modo=triagem`.** Priorização de fiscalização não precisa saber
qual veículo era, e ler placa sem necessidade cria dado pessoal sem finalidade
(`docs/legal/lgpd.md`). Este módulo só é acionado se e quando o modo de autuação
for habilitado.
