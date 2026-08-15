# demo/ — demonstração de produto (Opção A)

Página **self-contained** para a reunião de produto: o **painel real do ECOAR**
(o mesmo `dashboard/` da Opção B), semeado com o cenário de Piracicaba, num único arquivo
que abre por duplo-clique — **sem servidor e sem internet**, inclusive no celular.

```
demo/index.html   # abra no navegador
```

Publicada também como Artifact (link compartilhável).

## É a mesma tela da B — de propósito

A versão anterior desta demo era um painel desenhado à parte, e era de lá que
vinham os bugs visuais. Esta é montada a partir do dashboard real: mesmo HTML,
mesmo CSS, mesmo JavaScript. A **única** diferença é a camada de rede — as
chamadas `fetch` ao backend foram trocadas por leitura de um retrato congelado
dos dados (`dados-demo.js`). O que você vê é, byte a byte, a interface da B.

Isso é garantido por construção: `scripts/montar_demo.py` recorta os trechos de
rede do `dashboard/painel.js` e, se o painel mudar a ponto de o recorte não
casar, o build falha alto em vez de gerar tela quebrada.

## O cenário é Piracicaba, e os pontos não são chute

Os cinco pontos saíram de **levantamento documental** sobre o município, e cada
um carrega a razão dentro do produto — a coluna "Local" do painel diz por que
aquele ponto entrou:

| Ponto | Por que entrou |
|---|---|
| Av. Presidente Kennedy | onde a Semuttran já operou (ago/2023) |
| Área central / entorno hospitalar | reclamação de pacientes internados |
| Av. Dr. João Conceição (Paulista) | requerimento por escapamento e som |
| São Dimas | requerimento por perturbação do sossego |
| Rua do Porto / Beira-Rio | polo de lazer noturno |

Cada ponto tem **perfil horário próprio**: o corredor arterial satura no fim de
tarde, a Rua do Porto satura na madrugada de sexta e sábado, São Dimas é
incômodo de noite residencial. É o que faz o mapa de calor ter forma
reconhecível para quem mora na cidade.

As fontes, com o que foi conferido e o que ainda não foi, estão em
`docs/field-notes/piracicaba.md`.

**O que isso não é:** medição. Nenhuma gravação foi feita em Piracicaba. Os
pontos são reais e documentados; os **volumes e horários são construídos** para
a demonstração. Apresentar hipótese como medição é o jeito mais rápido de perder
a conta na primeira pergunta técnica — a demo diz isso na tela de acesso e no
tour.

## Tour guiado (primeiro acesso)

Ao entrar pela primeira vez, um **guia passo a passo** destaca cada tela e
explica o porquê de cada coisa — é o "modo TV de loja", que roda sozinho e ajuda
o apresentador. São dez passos (priorização → revisão → o porquê da decisão →
validação humana → auditoria). Fica gravado no navegador: só aparece no primeiro
acesso. O botão **?** no canto inferior esquerdo reabre o guia quando quiser.

O tour é exclusivo da demo (injetado no build, como a faixa "demonstração") — não
faz parte do dashboard real.

## O que ela mostra

- **Login** igual ao da B (qualquer token entra; um token com "operador" entra
  sem as telas de admin).
- **O porquê de cada evento** — cada evento traz um painel "Por que este
  resultado": o motivo determinístico do nó (por que **acionar**, **ambíguo** ou
  **descartar**) e o que o status significa (por que **pendente**, **confirmado**
  ou **rejeitado**). É a leitura em uma frase, para o apresentador e o operador.
- **Priorização** — mapa de calor hora × dia da semana + ranking dos cinco
  pontos de Piracicaba, sobre eventos confirmados. A coluna "Local" carrega a
  razão de cada ponto ter sido escolhido.
- **Fila de revisão** — evento com **áudio real** (embutido do pacote), imagens
  de câmera quando o gatilho acionou (rotuladas "captura simulada"), as regras
  determinísticas avaliadas pelo nó, o hash de integridade, e confirmar/rejeitar
  que **atualiza o estado na hora**.
- **Nós, Violações, Histórico, Métricas** — os mesmos dados do cenário.
- **Modelo e Auditoria** (perfil admin) — a trilha hash-chain com o indicador de
  integridade (356 entradas, íntegra).
- **Exportar relatório** — o relatório imprimível real, com as ressalvas
  jurídicas, aberto numa sobreposição.

## Como regenerar

O retrato dos dados sai do backend real semeado; a página é montada a partir do
dashboard. Dois passos:

```bash
python -m scripts.exportar_demo                 # gera demo/dados-demo.js (retrato da B)
python -m scripts.montar_demo --artifact=/tmp/demo-artifact.html
#   gera demo/index.html (standalone) e a versão só-conteúdo para o Artifact
```

## O que ela NÃO é

Um painel navegável com **dado de exemplo** — semeado para a demonstração, não é
captura de campo. Não lê placa, não gera multa, o SPL não tem valor legal. A
página carrega a faixa "demonstração · dados de exemplo" e as telas repetem essas
ressalvas — é o que dá credibilidade na primeira pergunta técnica.

O sistema de verdade é o `backend/` + `dashboard/` (a Opção B, em `deploy/`).
Esta demo é ele mesmo, congelado para caber num arquivo.
