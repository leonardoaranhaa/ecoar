# edge/ — nó de campo

Código que roda dentro da caixa IP65 no poste, num Raspberry Pi CM4. É o único
lugar do sistema que conversa com hardware físico.

## Encadeamento

```
audio_capture   4 microfones MEMS + buffer de 30s + SPL estimado + leitura do instrumento
      ↓
localization    de qual ângulo veio o som (GCC-PHAT)
      ↓
classifier      que som foi esse, com score de confiança
      ↓
camera_trigger  decide: aciona / ambíguo / descarta — e aciona a câmera se for o caso
      ↓
evidence_packager   monta o pacote assinado (áudio + imagem + metadado + hash)
      ↓
uplink          fila persistente e envio ao backend via 4G
```

`tamper_detection` corre em paralelo, fora dessa cadeia: é ocorrência
patrimonial, não evento de fiscalização, e tem prioridade máxima no `uplink`.

## Regra que vale para todo módulo desta pasta

Nenhuma biblioteca de hardware (`sounddevice`, `serial`, `smbus2`, `gpiozero`,
`cv2`) pode ser importada no topo de um arquivo. Importa-se dentro do driver
específico, sob demanda. Cada periférico tem interface abstrata + implementação
real + implementação simulada, para que a cadeia inteira rode e seja testada
numa máquina sem nenhum componente físico (decisão D11).
