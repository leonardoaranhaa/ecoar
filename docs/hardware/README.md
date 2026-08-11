# docs/hardware — o lado físico

Pinagem, montagem e checkpoints de integração entre o hardware e o código.

## Mapa de conexões do nó

```
   4x microfone MEMS ICS-43434 ──(I2S)──┐
                                         │
   Instrumento de medição (NMT) ─(rede/serial)─┤
                                         ├──► Raspberry Pi CM4 ──(USB)──► Modem 4G Quectel EC25
   Câmera ANPR ─────────────(USB/CSI)───┤        (caixa IP65)
                                         │
   MPU-6050 ────────────────(I2C)───────┤
   Reed switch ─────────────(GPIO)──────┘
                       ▲
                       │
          Fonte 12V + bateria de backup 7Ah
```

Tudo converge no CM4 — é o único ponto que conversa com todos os periféricos.

## Ordem de integração (uma peça por vez)

Cada etapa tem um checkpoint que precisa passar antes da seguinte. Integrar tudo
de uma vez e depois debugar é o caminho mais caro.

| # | Etapa | Checkpoint |
|---|---|---|
| 1 | Preparar o CM4 (SO, SSH, I2S, serial, câmera, venv) | acesso por SSH e ambiente virtual funcionando |
| 2 | Array de microfones isolado | 4 canais gravam áudio distinto e sincronizado; palma perto de um mic gera pico no canal certo |
| 3 | Instrumento de medição (só em `modo=autuacao`) | valor lido por código bate com o da plataforma do fabricante em 5 medições de volumes diferentes |
| 4 | Câmera isolada | placa legível na distância real de instalação, de dia e à noite |
| 5 | Modem 4G | internet pelo 4G com o Wi-Fi desligado |
| 6 | Cadeia completa | um som de teste percorre do array até a fila de revisão do dashboard, sem etapa pulada |

Só depois do checkpoint 6 validado **em bancada** faz sentido subir no poste.

## Restrições físicas que já são decisão

- **Caixa IP65, não IP68.** Vedação total impediria o som de chegar ao array.
- **Antena 4G externa ao gabinete.** Caixa metálica atenua o sinal; a passagem
  precisa ser vedada.
- **A cápsula do instrumento certificado fica exposta ao ar**, em haste curta,
  com kit anti-vento/chuva/pássaro — como a lente de uma câmera fica para fora
  do invólucro. É parte do conjunto, não equipamento avulso em tripé.
- **Nunca abrir o invólucro do instrumento certificado.** Invalida a
  certificação. A integração é de dados.
- **Instalação a 4,5–5 m de altura**, em ponto iluminado, de preferência no
  campo de visão de câmera municipal já existente.
- **Enquadramento da câmera captura placa e veículo, não o rosto do condutor**
  (`docs/legal/lgpd.md`).

## Erros comuns

| Sintoma | Causa provável |
|---|---|
| Áudio cortado ou com ruído estranho | alimentação instável — fonte dedicada para os microfones |
| Ângulo sempre errado com áudio limpo | geometria configurada não bate com a montagem física; medir de novo com régua |
| Câmera aciona mas a placa sai ilegível | distância além do foco, ou falta de IR à noite |
| Instrumento não responde na serial | baud rate errado — cada fabricante define o seu |
| 4G conecta e cai | antena mal posicionada; pode precisar de cabo mais longo até ponto de melhor sinal |
| Pacote chega incompleto no backend | erro silencioso em algum módulo — subir o nível de log do orquestrador |
