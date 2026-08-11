# edge/camera_trigger — decidir e acionar

Recebe o score do classificador e o ângulo da localização, e decide se a câmera
dispara. É o módulo mais curto do sistema e o de maior peso jurídico.

## Três saídas, não duas

| Decisão | Quando | O que acontece |
|---|---|---|
| `acionar` | score acima do limiar alto **e** ângulo dentro do campo de visão | câmera dispara, evento segue para o pacote de evidência |
| `ambiguo` | score intermediário, ângulo incerto, ou qualquer subsistema indisponível | evento é registrado **sem** disparar a câmera, marcado para revisão |
| `descartar` | score abaixo do limiar baixo, ou classe não-alvo com alta confiança | nada é capturado |

A existência da faixa `ambiguo` é deliberada: um sistema com só "dispara / não
dispara" precisa fingir certeza que não tem. Registrar a dúvida como dúvida é o
que sustenta a taxa de falso positivo baixa e o argumento perante contestação.

## Determinismo

A decisão é uma tabela de regras explícita, com versão de política gravada em
cada evento. Mesma entrada + mesma versão = mesma saída, sempre. Nenhuma parte
dessa decisão usa modelo de linguagem ou heurística não registrada.

## Fail-closed

Se o classificador não responder, a decisão é `ambiguo` com motivo explícito —
nunca `descartar` em silêncio, nunca `acionar` por precaução.
