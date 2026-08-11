# backend/review_queue — validação humana

A tela de maior uso diário do sistema, e a etapa que o desenho inteiro protege:
nenhum evento vira estatística de priorização, dado de treino ou rascunho de
autuação sem passar por aqui.

## Estados de um evento

```
pendente_revisao ─┬─► confirmado        (evento real; entra na priorização e é
                  │                       elegível a virar dado de treino)
                  ├─► confirmado_multa  (somente em modo=autuacao)
                  └─► rejeitado         (não vira multa nem dado de treino;
                                          mídia expurgada em prazo curto)
```

Toda decisão grava quem decidiu, quando, e observação opcional — e vai para a
trilha de auditoria. Um evento decidido não volta a `pendente_revisao`: correção
é uma nova decisão registrada por cima, com histórico preservado.
