# edge/audio_capture — captura de áudio

Ponto de entrada de todo o sistema. Mantém sempre os últimos 30 segundos de
áudio dos 4 microfones em memória, para que, quando um pico de som acontece, o
sistema consiga recuperar o que veio **antes** do pico — e não só depois.

## Responsabilidades

1. Capturar áudio simultâneo dos 4 microfones MEMS I2S (ICS-43434), com
   timestamps sincronizados entre canais.
2. Manter buffer circular de 30 s.
3. Calcular SPL aproximado em tempo real a partir do array.
4. Ler o instrumento de medição certificado através de uma camada de adaptação
   isolada.
5. Expor uma interface simples para `localization` e `classifier` consumirem.

## Distinção que não pode ser perdida

O array MEMS **não é** a fonte da medição oficial de dB para fins legais. O SPL
calculado a partir dele é estimativa relativa, calibrada por campanha, e serve
para acionar o classificador e a localização — nada além disso. Todo valor que
sai daqui carrega `valor_legal: false`.

A medição com validade legal vem de um instrumento certificado IEC 61672
(estação de monitoramento permanente, NMT), integrado por dados, e só é
necessária em `modo=autuacao`. Ver `docs/legal/inmetro.md`.

## Camada de adaptação do instrumento

A leitura do instrumento fica atrás da interface `SonometroReader`. Trocar de
modelo (Classe 2 na validação → Classe 1 na produção) altera **apenas** uma
classe deste módulo. Nenhum outro módulo do ECOAR conhece o protocolo do
fabricante — cada um define baud rate, comando e formato de resposta próprios.

Implementações prontas: `SonometroAusente` (padrão em triagem — falha
explicitamente em vez de inventar valor), `SonometroMock` (desenvolvimento) e
`SonometroSerialGenerico` (molde para o modelo real). `criar_sonometro()` recusa
instrumento simulado em `modo=autuacao`, mesmo que a configuração seja montada
na mão.

## Arquivos

| Arquivo | Papel |
|---|---|
| `fontes.py` | interface `FonteAudio` + `FonteI2S` (array real), `FonteWav` (gravação de campo), `FonteSintetica` (bancada) |
| `buffer.py` | anel de 30 s com mapeamento índice ↔ tempo; é o que permite recuperar o áudio anterior ao pico |
| `spl.py` | SPL estimado com ponderação A; toda saída carrega `valor_legal: false` |
| `sonometro.py` | camada de adaptação do instrumento — **o único arquivo que conhece o protocolo** |
| `captura.py` | serviço que junta tudo e entrega `janela_evento()` aos módulos seguintes |
| `sintetico.py` | cena acústica de bancada, com TDOA correto para um azimute escolhido |
| `main.py` | teste de bancada (checkpoint 2) |
| `read_sonometro.py` | leitura isolada do instrumento (checkpoint 3) |

## Usar

Teste de bancada da captura, com o array conectado:

```bash
python -m edge.audio_capture.main --config config/no.exemplo.yaml --duracao 10
```

O teste da palma: bata palma perto de **um** microfone e confira se o pico
aparece no canal correspondente. Todos os canais reagindo igual significa
microfones somados; um canal mudo é montagem elétrica, não software.

Sem hardware nenhum:

```bash
python -m edge.audio_capture.main --fonte sintetica --azimute 90 --duracao 6
python -m edge.audio_capture.main --arquivo gravacao-campo.wav --duracao 30
```

Leitura isolada do instrumento (checkpoint 3 — o valor lido tem que bater com o
da plataforma do fabricante em pelo menos 5 níveis diferentes):

```bash
python -m edge.audio_capture.read_sonometro --config config/no-01.yaml -n 5
```

## Consumir daqui

```python
from edge.audio_capture import CapturaAudio
from edge.config import carregar

with CapturaAudio(carregar("config/no-01.yaml")) as captura:
    spl = captura.spl_atual()                       # pré-gatilho barato
    evento = captura.janela_evento(instante_pico)   # 10 s antes + 10 s depois
    evento.amostras       # (n, 4) float32 — vai para localization e classifier
    evento.spl            # estimativa do array, valor_legal=False
    evento.sonometro      # None em triagem, com o motivo em motivo_sem_sonometro
```

## Sobre a cena sintética

`sintetico.py` gera 4 canais coerentes com o atraso de chegada correto para um
azimute escolhido. Serve para exercitar a cadeia sem microfone — **não é dado de
treino**. Um classificador treinado nesses sinais aprende a reconhecer esses
sinais, não escapamento adulterado de verdade.
