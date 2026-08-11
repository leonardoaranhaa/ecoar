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

## Como usar

```python
from edge.tamper_detection import criar_detector

detector = criar_detector(config, ao_alerta=enfileirar, capturar_imagem=fotografar)
with detector:
    ...  # vigia em segundo plano
```

No nó, o `edge/no.py` já liga o detector: `ao_alerta` enfileira com prioridade
máxima no uplink, e `capturar_imagem` dispara a câmera antes de tudo.

## Sensores atrás de interface (D11)

| Sinal | Sensor real | Simulado |
|---|---|---|
| impacto, inclinação, movimento | MPU-6050 (I2C) | `SensorInercialSimulado` |
| abertura da tampa | reed switch (GPIO) | `SensorAberturaSimulado` |
| queda de energia | INA219 / GPIO | `SensorAlimentacaoSimulado` |

`smbus2` e `gpiozero` são importados dentro do driver. A cadeia de alerta inteira
roda e é testada sem nenhum sensor físico — os eventos são injetados por
`simular_impacto()`, `simular_abertura()` etc.

## Dois detalhes que evitam alarme falso

**Referência de inclinação é a posição de instalação, não a vertical.** O nó
pode ser montado torto de propósito; o que dispara é a *mudança* em relação a
como foi instalado. `sair_manutencao()` recalibra, porque a montagem pode ter
mudado durante a manutenção.

**Abertura e queda de energia disparam só na borda.** Uma tampa aberta gera um
alerta, não um a cada 0,1 s enquanto continua aberta.

## Ordem de ação sob violação

O tempo de vida restante do equipamento pode ser de segundos, então a ordem é
fixa:

1. **fotografa** — a tentativa de furto vira a própria evidência;
2. **registra local** — se a transmissão falhar e o equipamento for recuperado,
   o alerta ainda está no disco;
3. **enfileira com prioridade máxima** — à frente de qualquer pacote acústico.

A captura falhar (câmera arrancada junto) não impede o alerta de sair: ele vai
sem imagem. Existe teste para isso.

## Canal separado (D14)

O alerta trafega por `/v1/alertas`, não pela fila de fiscalização. No backend
ele cai na tabela `violacoes` e na trilha de auditoria como `alerta_violacao` —
nunca com conteúdo de placa. É ocorrência patrimonial, não evento de
fiscalização, e o dashboard as separa.

## Modo manutenção

`entrar_manutencao()` suspende os alertas para a equipe abrir o gabinete
legitimamente. **Expira sozinho**, com teto na configuração: não existe forma de
deixar o alarme desligado por esquecimento.
