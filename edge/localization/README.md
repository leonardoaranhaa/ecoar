# edge/localization — de onde veio o som

Sem este módulo, o sistema só sabe que "algo bateu 80 dB". Com ele, sabe de qual
direção o som veio — que é o que permite apontar a câmera para o veículo certo e
sustentar, na evidência, que o som veio daquele veículo e não de outro na via.

## Como funciona, em linguagem simples

**O princípio.** Um som que chega de lado atinge um microfone antes do outro. A
diferença é minúscula — o array inteiro tem 9 cm, e o som atravessa isso em
262 milionésimos de segundo — mas é mensurável, e é ela que carrega a direção.

**Passo 1: medir a diferença de tempo entre dois microfones.** Desliza-se um
sinal sobre o outro e procura-se o deslocamento em que eles mais se parecem.
Esse é o método da correlação cruzada.

**Passo 2: o truque que faz funcionar na rua.** Antes de comparar, o método
joga fora a informação de *intensidade* de cada frequência e mantém só a de
*fase*. Isso é o "PHAT" do nome. Parece perda de informação, mas é o contrário:
o resultado deixa de depender do timbre do som e passa a depender só do tempo,
e o pico de coincidência fica muito mais estreito. Com eco de parede e fachada,
é a diferença entre uma estimativa utilizável e uma inútil.

**Passo 3: do tempo para o ângulo.** Com 4 microfones há 6 pares, e portanto 6
diferenças de tempo medidas. A geometria do array diz, para cada ângulo
possível, quais deveriam ser essas 6 diferenças. O ângulo escolhido é o que
melhor explica as seis ao mesmo tempo — não o que casa com um par sozinho.

**Passo 4: dizer o quanto se confia.** Se um único ângulo explica bem as seis
medições, a estimativa é sólida. Se nenhum ângulo explica (dois veículos juntos,
som refletido, ou nada além de rua), o desacordo aparece como resíduo alto, e a
confiança cai. O módulo devolve o ângulo **e** essa margem — apontar sem dizer o
quanto se sabe é o que perde na contestação.

É a mesma matemática que assistentes de voz usam para saber de que lado da sala
alguém falou. Engenharia madura aplicada a um problema novo, não pesquisa.

## Por que 4 microfones em círculo, e não 2

Dois microfones não distinguem frente de trás: um som vindo de 60° e outro
vindo de 300° chegam com exatamente a mesma diferença de tempo. Quatro em
círculo resolvem, porque os pares apontam para direções diferentes e a
ambiguidade de um par é desfeita pelos outros. Existe teste para isso.

## Precisão medida

Varredura em bancada, array de 4,5 cm de raio, cena sintética com ruído de fundo:

```
python -m edge.localization.main --varrer

   real  estimado    erro   margem   conf   resíduo
    0.0     359.9    -0.0     1.0°   1.00      2.1 µs
   90.0      89.6    -0.4     2.0°   0.99      4.1 µs
  180.0     179.0    -1.0     2.0°   1.00      3.1 µs
  270.0     268.8    -1.2     1.0°   1.00      1.7 µs

erro médio 0.45° · pior caso 1.25° · meta do projeto ±5°
```

Isso é o erro do **algoritmo**, em sinal sintético. O erro em campo será maior:
reverberação, vento, dois veículos, e imprecisão da montagem física entram
depois. A varredura serve para garantir que o algoritmo não é o gargalo, e para
detectar regressão quando alguém mexer nos parâmetros.

## Dois ajustes que não são detalhe

**Banda limitada.** Acima da frequência de ambiguidade do array (≈1,9 kHz para
raio de 4,5 cm) a fase se repete entre os microfones mais afastados, e a
estimativa passa a mentir. Abaixo de 150 Hz o que existe é vento e rumor de
tráfego. O módulo trabalha entre esses dois limites, calculados a partir da
geometria configurada — não são números fixos no código.

**Descarte das raias de ruído.** O PHAT clássico normaliza toda raia de
frequência para magnitude 1, inclusive as que contêm apenas rua. Um escapamento
tem espectro de linhas: quase toda a energia está em poucas dezenas de raias
harmônicas, e as milhares restantes são ruído. Normalizadas, elas entram com o
mesmo peso e afogam a estimativa. Medido na bancada: PHAT puro erra ~64 µs de
TDOA; descartando as raias abaixo de 2% da magnitude máxima e usando expoente
0,75, o erro cai para ~3 µs — de dezenas de graus para menos de um.

## Dois erros de montagem, dois sintomas diferentes

Vale saber distinguir, porque a confusão entre eles custa tempo no poste.

| Erro de montagem | O que acontece | Como aparece |
|---|---|---|
| **Raio configurado ≠ raio real** | todos os tempos escalam por igual; nenhum ângulo explica as medições | resíduo estoura, confiança vai a zero — o sistema declara que não sabe |
| **Array girado no poste sem `azimute_offset_graus`** | as medições continuam consistentes entre si | resíduo baixo, confiança alta, e **todos** os ângulos deslocados pelo mesmo tanto |

O segundo é o perigoso: não dá sintoma interno. Só a comparação com a via real
denuncia. Por isso o checkpoint de instalação inclui apontar uma fonte conhecida
de um ângulo conhecido antes de considerar o nó operacional.

O sinal do offset também confunde: array girado +30° faz o mundo, visto por ele,
girar −30°.

## Usar

```python
from edge.geometria import ArrayCircular
from edge.localization import Localizador

localizador = Localizador(ArrayCircular.de_config(config.array))
estimativa = localizador.estimar(evento.amostras, evento.taxa_amostragem)

estimativa.azimute_graus   # 0° = direção do microfone 0 + offset, anti-horário
estimativa.confianca       # 0..1
estimativa.margem_graus    # faixa de ângulos igualmente plausíveis
estimativa.residuo_us      # desacordo entre os pares
```

Trecho longo não vai inteiro para a FFT: o módulo recorta automaticamente a
parte mais energética da janela, que é onde o evento está.

## Convenção de ângulo

Vale em todo o sistema: azimute em graus, 0° na direção do microfone 0 mais o
offset de instalação, sentido anti-horário visto de cima, e é a direção de onde
o som **vem**.
