# edge/classifier — que som foi esse

O anti-falso-positivo do sistema, e o principal diferencial técnico frente aos
sistemas de referência (São José dos Campos, Curitiba), que acionam por decibel
puro.

## O problema que resolve

Acionar câmera por limiar de dB dispara com buzina, britadeira e trovão. Isso
gasta processamento, enche a fila de revisão de lixo e enfraquece a evidência.

## Abordagem

1. Extrair o espectrograma (log-mel) do trecho de áudio.
2. Classificar a assinatura entre: escapamento adulterado, buzina, obra, trovão,
   som ambiente.
3. Devolver classe prevista **e score de confiança** — o score é o que alimenta
   a decisão de acionar, ficar ambíguo, ou descartar (`edge/camera_trigger`).

O score é o "verificado vs. inferido" aplicado a áudio: alta confiança aciona a
câmera; padrão ambíguo registra o evento mas não aciona sozinho.

## Sobre os dados de treino

Não existe dataset público brasileiro para isso. O modelo inicial é
pré-treinado com áudio adaptado por *data augmentation* (ruído urbano,
reverberação, atenuação por distância) e **é provisório**. Ele precisa ser
re-treinado com gravação de campo real de Bauru antes de qualquer operação — e
depois disso, apenas com dado confirmado por operador humano (decisão D13).
