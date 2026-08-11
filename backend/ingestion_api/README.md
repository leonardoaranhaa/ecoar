# backend/ingestion_api — porta de entrada

Recebe do nó de campo:

- pacotes de evidência acústica (formato de `edge/evidence_packager`);
- alertas de violação patrimonial (canal separado, prioridade máxima);
- heartbeats de saúde do nó.

## O que faz com um pacote

1. autentica o nó por token;
2. revalida o SHA-256 do manifesto e de cada arquivo de mídia — **rejeita** se
   não bater;
3. armazena a mídia estruturada por data e nó (armazenamento local no MVP,
   trocável por object storage sem redesenho);
4. cria o evento no banco com status `pendente_revisao`;
5. registra na trilha de auditoria;
6. confirma o recebimento ao nó, que só então apaga o pacote da fila local.

Autenticação por token estático entre nó e API é suficiente para o MVP. Antes de
operação contratada, migrar para certificado por nó (mTLS).
