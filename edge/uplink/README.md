# edge/uplink — envio ao backend

O nó fica num poste, com 4G que cai. Enviar direto e torcer para dar certo
perderia evidência.

## Desenho

Fila persistente em disco (sobrevive a reboot e a corte de energia), com
prioridade e retentativa com espera progressiva.

| Prioridade | Conteúdo |
|---|---|
| 0 (máxima) | alerta de violação patrimonial |
| 5 | pacote de evidência acústica |
| 9 | heartbeat |

Um pacote só sai da fila depois que o backend confirma recebimento **e** valida
o hash. Confirmação parcial não apaga nada.
