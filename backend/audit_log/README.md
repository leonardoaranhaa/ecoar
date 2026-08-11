# backend/audit_log — trilha de auditoria

Registra, em cadeia encadeada por hash:

- cada evento recebido pela ingestão (e cada pacote rejeitado, com o motivo);
- cada ação de revisão humana: quem confirmou ou rejeitou, quando;
- cada ciclo de re-treino e cada promoção ou reversão de modelo;
- cada acesso ao pacote de evidência de um evento específico;
- cada alerta de violação patrimonial;
- cada troca de modo de operação.

## Hash-chain

Cada entrada inclui o hash da entrada anterior. Alterar ou remover qualquer
entrada do histórico quebra a cadeia a partir dali, e a quebra é detectável por
qualquer pessoa que rode a verificação — inclusive a defesa de um autuado.

É isso que separa "temos um log" de "temos uma trilha que resiste a
contestação".

## Regra de conteúdo

A trilha registra **que** algo aconteceu, com identificador de evento, operador
e timestamp. Ela não duplica conteúdo de mídia nem armazena texto de placa.
