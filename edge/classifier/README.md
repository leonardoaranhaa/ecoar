# edge/classifier — que som foi esse

O anti-falso-positivo do sistema, e o principal diferencial técnico frente aos
sistemas de referência (São José dos Campos, Curitiba), que acionam por decibel
puro.

## O problema que resolve

Acionar câmera por limiar de dB dispara com buzina, britadeira e trovão. Isso
gasta processamento, enche a fila de revisão de lixo e enfraquece a evidência.

## Duas implementações, uma interface

| | `ClassificadorHeuristico` | `ClassificadorCNN` |
|---|---|---|
| Como decide | regras explícitas sobre descritores físicos | rede convolucional sobre espectrograma mel |
| Explica a decisão | em português, citando as medidas | só o score |
| Determinístico | sim, por construção | sim, com modelo fixo |
| Precisa de dado de treino | não | sim — gravação de campo rotulada |
| Papel | referência, explicabilidade e piso de segurança | caminho de produção |

Ambas implementam `Classificador`. O `camera_trigger` não sabe qual está
rodando — mas **a evidência sabe**: cada predição carrega `modelo` e
`versao_modelo`.

Com `classificador.tipo: auto`, o nó prefere a rede e cai para o classificador
de referência se o modelo não carregar, registrando a degradação no log e na
evidência. Com `tipo: cnn`, o modelo é obrigatório e o nó não sobe sem ele —
que é o certo quando alguém declarou explicitamente qual modelo quer em
produção.

## Descritores: números com significado físico

O classificador de referência não trabalha com coeficientes opacos, e sim com
grandezas que dá para explicar numa reunião:

| Descritor | O que captura | Por que importa |
|---|---|---|
| `f0_hz` | fundamental | motor vive em 60–120 Hz; buzina, acima de 300 |
| `forca_harmonica` | energia nas harmônicas de f0 | escapamento e buzina são harmônicos; obra e trovão, não |
| `taxa_impulsos_hz` | estalos por segundo | escapamento estala rápido; rompedor, ~12 vezes por segundo |
| `energia_grave` / `energia_aguda` | distribuição espectral | trovão é quase todo grave |
| `crista` | pico sobre média da envoltória | separa evento de rumor contínuo |
| `duracao_ativa_s` | quanto tempo o som esteve forte | passagem é transitória; tráfego de fundo, não |
| `planicidade` | tonal vs. ruidoso | ruído branco é plano; motor, não |

A saída inclui a frase de explicação: *"a favor: fundamental grave de motor
(55–140 Hz); série harmônica forte; estalo rápido de explosão (fundamental
84 Hz, harmônicas 0.82, 47 impulsos/s, grave 0.51)"*.

## Uma armadilha que virou teste

As duas notas de uma buzina (440 e 554 Hz) **batem em 114 Hz** — dentro da
faixa de rotação de motor. Estimar a fundamental por autocorrelação, que é o
caminho óbvio, faz a buzina ser lida como fundamental de 114 Hz e passar por
escapamento: exatamente o falso positivo que este módulo existe para evitar.

Por isso a fundamental vem da **raia espectral forte de menor frequência**, com
exigência de proeminência sobre a vizinhança (que também impede ruído de banda
larga de produzir uma fundamental inventada). Existe teste para o caso da
buzina.

## Resultado na bancada

```
python -m edge.classifier.main --bancada

perfil          escapament      buzina        obra      trovao    ambiente
escapamento           0.70        0.03        0.06        0.22        0.00   ok
buzina                0.08        0.70        0.15        0.08        0.00   ok
obra                  0.10        0.20        0.66        0.04        0.00   ok
trovao                0.15        0.02        0.23        0.59        0.00   ok
ambiente              0.34        0.03        0.01        0.24        0.38   ok
ruído branco          0.02        0.10        0.07        0.04        0.77
```

**Isto não é evidência de acerto em campo.** A cena sintética foi escrita por
nós, e um classificador calibrado contra ela acerta por construção. O número
que importa — taxa de falso positivo real — só existe depois de gravação em
Bauru.

Note a linha `ambiente`: 0,38 contra 0,34 de escapamento. Rumor de tráfego
grave e contínuo é a confusão mais provável deste classificador, e está
registrada aqui de propósito em vez de escondida com mais ajuste fino. Na
prática o evento cairia como **ambíguo** na etapa de decisão, que é o
comportamento correto para um caso genuinamente ambíguo.

## Sobre os dados de treino

Não existe dataset público brasileiro para isso. O caminho é:

1. gravar campo nos pontos críticos de Bauru (Ponte São João, Centro);
2. rotular manualmente;
3. multiplicar com `augment.py`, que simula condição de rua sobre áudio limpo —
   distância (perda de 6 dB por dobro, mais absorção do agudo pelo ar),
   reverberação de fachada, e ruído urbano com espectro de tráfego;
4. treinar com `treino.py`;
5. daí em diante, só dado **confirmado por operador humano** entra em novo
   treino (D13).

Aumento de dados não substitui gravação real. Um modelo treinado só com áudio
aumentado é um modelo não validado.

## Cuidado que o `treino.py` aplica sozinho

A divisão treino/validação é **por arquivo de origem**, não por amostra: todas
as variações geradas a partir do mesmo áudio ficam do mesmo lado. Sem isso, a
validação vê uma cópia processada do que o treino já viu e devolve uma acurácia
que não existe. E o conjunto de validação nunca recebe aumento. Existe teste
que falha se esse vazamento voltar.

## Usar

```bash
python -m edge.classifier.main --bancada                    # regressão
python -m edge.classifier.main --arquivo gravacao.wav       # sobre campo
python -m edge.classifier.treino --dados acervo/ --saida modelos/2026-09.pt
```

```python
from edge.classifier import criar_classificador

classificador = criar_classificador(config)
predicao = classificador.classificar(evento.amostras, evento.taxa_amostragem)

predicao.classe        # classe vencedora
predicao.score_alvo    # o que decide o acionamento — não é o mesmo que score
predicao.explicacao    # por que, em português
```

`score` e `score_alvo` são coisas diferentes, e confundir os dois é como um
acionamento errado nasce: uma buzina classificada com 0,9 de certeza tem
`score` alto e `score_alvo` baixo. Quem decide o disparo é o segundo.

## Fail-closed

`ClassificadorIndisponivel` nunca vira "provavelmente não era nada". Quem chama
trata como evento **ambíguo**: registra sem acionar a câmera (D8).
