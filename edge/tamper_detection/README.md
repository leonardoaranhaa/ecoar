# edge/tamper_detection — proteção patrimonial

Equipamento em via pública é alvo. Este módulo garante que o alerta e a
evidência saiam **antes** de o equipamento ser removido ou desligado.

## O que detecta

| Sinal | Sensor | O que indica |
|---|---|---|
| Impacto | acelerômetro MPU-6050 (I2C) | pancada no gabinete |
| Inclinação anômala | MPU-6050 vs. posição de referência calibrada na instalação | suporte sendo torcido |
| Movimento contínuo | MPU-6050 | equipamento sendo carregado |
| Abertura da tampa | chave magnética (reed switch, GPIO) | gabinete aberto |
| Queda de energia | transição para bateria de backup | corte de alimentação |

Cada um com limiar próprio e configurável — vento, vibração de tráfego pesado e
poste levemente atingido não podem virar alarme falso.

## Ordem de ação sob violação

O tempo de vida restante do equipamento pode ser de segundos. Por isso a ordem é
fixa:

1. dispara captura de imagem (reutiliza a interface de câmera do
   `edge/camera_trigger`);
2. envia alerta ao backend com prioridade máxima, **à frente** de qualquer
   pacote acústico pendente na fila;
3. registra localmente, para o caso de a transmissão falhar e o equipamento ser
   recuperado depois.

A tentativa de furto vira a própria evidência.

## Heartbeat e modo manutenção

O nó envia sinal de vida periódico com status de bateria e saúde dos sensores.
Ausência de heartbeat acende alerta no dashboard.

O **modo manutenção**, acionado por autenticação, suspende os alertas
temporariamente para a equipe abrir o gabinete legitimamente. Ele expira sozinho
— não existe forma de deixar o alarme desligado por esquecimento.

## Canal separado

Alerta de violação **não** entra na fila de eventos acústicos. É ocorrência
operacional/patrimonial, tem endpoint próprio no backend e tela própria no
dashboard (decisão D14).
