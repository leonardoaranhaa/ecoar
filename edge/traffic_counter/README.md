# edge/traffic_counter — contagem e classificação de tráfego

Reaproveita a câmera ANPR já instalada, mas roda em paralelo ao pipeline
acústico: amostra em cadência fixa (`trafego.cadencia_s`), não por evento de
som. É o Nível 1 do roadmap modular (`docs/projeto/manual-tecnico.md` seção
12.1, Prompt 13 em `docs/projeto/prompts-claude-code.md`).

## O que este módulo garante

1. **Não lê placa.** Isso é `vision/plate_ocr` (D10), roda no backend, e
   continua desligado em `modo=triagem`. Este módulo não recebe a imagem para
   OCR, só para classificação de tipo.
2. **Não guarda quadro a quadro.** O quadro capturado é descartado logo depois
   da classificação — o que sai deste módulo é contagem agregada por
   dia/hora/tipo, nunca imagem.
3. **Não gera dado de fiscalização.** Contagem de tráfego não vira estatística
   de priorização de ruído nem evidência de infração — é dado de planejamento
   de mobilidade, à parte da fila de revisão (D2 não se aplica aqui pelo
   mesmo motivo: não há decisão de infração para validar).
4. **Desligado por padrão.** `trafego.habilitado: false` é o valor de partida.

## Classificador

`ClassificadorVeiculo` é a interface (D11 — hardware/modelo sempre atrás de
interface, com implementação simulada). A única implementação hoje é
`ClassificadorSimulado`: gera uma distribuição de tipos plausível sem olhar o
quadro de verdade, para permitir desenvolver e demonstrar o pipeline inteiro
(agregação → envio → dashboard) antes de existir um modelo real integrado.

**Diferença importante em relação ao classificador acústico de escapamento**:
lá não existe dataset público equivalente, e o modelo precisa ser treinado do
zero com gravação de campo. Aqui existe modelo pré-treinado público de
detecção de veículo por tipo (ex.: um detector tipo YOLO-nano ou
MobileNet-SSD já treinado em classes de veículo comuns) — o próximo passo real
é integrar um desses, não treinar do zero. `trafego.classificador: "modelo"`
está reservado para essa implementação futura; hoje ela levanta
`NotImplementedError` explicitamente, em vez de cair silenciosamente para o
simulado.

## Precisão

A contagem é aproximada — limitação de qualquer classificador de visão em
condição real de rua, ângulo de câmera, iluminação noturna. Não tem qualquer
finalidade de fiscalização.
