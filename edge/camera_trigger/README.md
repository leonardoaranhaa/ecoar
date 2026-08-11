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

## Como usar

```python
from edge.camera_trigger import AcionadorCamera

with AcionadorCamera(config) as acionador:
    resultado = acionador.processar(evento_id, predicao, doa, spl)

resultado.decisao.acao          # Acao.ACIONAR | AMBIGUO | DESCARTAR
resultado.decisao.gera_evento   # ambíguo também é evento, só que sem imagem
resultado.decisao.regras        # toda regra avaliada, com esperado e medido
resultado.capturas              # imagens gravadas, vazio se não acionou
resultado.falha_de_captura      # câmera falhou? o evento continua valendo
```

## O que vai para a evidência

Não sai um veredito solto. Sai a decisão **com todas as regras avaliadas**,
cada uma com o que se esperava, o que se mediu e se passou:

```json
{"acao": "ambiguo",
 "motivo": "score compatível, mas fonte dentro do campo de visão da câmera",
 "versao_politica": "politica/1.0",
 "regras": [
   {"nome": "score da classe alvo acima do limiar de acionamento",
    "atendida": true, "esperado": ">= 0.80", "medido": "0.950 (classe escapamento_adulterado)"},
   {"nome": "fonte dentro do campo de visão da câmera",
    "atendida": false, "esperado": "desvio <= 45.0° do eixo da câmera",
    "medido": "160.0° (fonte em 170.0°)"}]}
```

É o que transforma "o sistema decidiu" em "o sistema decidiu por estas razões".

## Limiares por nó, versão por política

Os limiares moram na configuração do nó (`gatilho:`), não no código: uma via de
tráfego pesado tem piso de ruído diferente de uma rua residencial, e o campo de
visão depende de como a câmera foi apontada naquele poste.

A `versao_politica` é gravada em cada evento. **Mudou limiar, muda a versão** —
sem isso é impossível responder, seis meses depois, por que um evento acionou e
outro não. E essa é exatamente a pergunta que uma contestação faz.

## Se a câmera falhar

O evento não é perdido. Áudio, ângulo e score continuam valendo, o evento vai
para revisão sem imagem, e a falha entra no pacote de evidência
(`falha_de_captura`). Perder o evento inteiro porque o sensor de imagem não
respondeu seria trocar um problema por um maior.

## A captura simulada se declara simulada

A imagem gerada pela `CameraSimulada` é um padrão de teste obviamente
artificial, e não uma foto plausível de veículo com placa. Isso é deliberado:
uma captura simulada que parece real pode acabar num relatório ou numa
demonstração sem ninguém perceber que é inventada. O campo `simulada: true`
viaja junto no manifesto.
