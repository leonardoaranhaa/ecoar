# dashboard/ — plataforma de gestão

Interface web servida pelo próprio backend. Sem etapa de build: HTML + CSS + JS.
Dependência de node no município é atrito que não paga.

## Telas

| Tela | Quem vê | O que faz |
|---|---|---|
| **Priorização** (home) | todos | mapa de calor hora × dia da semana + ranking de pontos, sobre eventos **confirmados**. O entregável central em modo de triagem, e por isso a home |
| Fila de revisão | todos | áudio, imagem, ângulo, score e as regras avaliadas pelo nó, com confirmar/rejeitar |
| Nós | todos | online/sem sinal (15 min sem heartbeat), bateria, pendentes, último contato |
| Violações | todos | canal patrimonial, separado da fiscalização (D14) |
| Histórico | todos | eventos já decididos, com filtro por status |
| Métricas | todos | volume por dia, taxa de rejeição na revisão |
| Modelo | **admin** | versões de classificador vistas na evidência |
| Auditoria | **admin** | cadeia de hash com indicador de integridade |
| Configurações | todos | modo por nó, e por que a autuação está bloqueada |

## RBAC em duas camadas

O menu esconde Modelo e Auditoria de quem não é admin — **e o backend recusa de
novo** (403) mesmo que o endpoint seja chamado direto. A garantia mora no
backend; o menu é só conveniência. `GET /v1/eu` diz ao painel quem está logado.

## Priorização é o produto em triagem

O mapa de calor responde "onde e quando", que é o que a prefeitura leva para a
equipe de blitz. Só entra evento **confirmado por operador** (D2): priorizar
sobre evento pendente ou rejeitado mandaria a fiscalização para o lugar errado.

O botão de exportação gera um relatório HTML pronto para imprimir em PDF — sem
biblioteca de PDF no servidor, o operador imprime pelo navegador. O relatório
carrega as ressalvas jurídicas: baseado em confirmações humanas, não constitui
auto de infração, SPL sem valor legal.

## O que a tela de configurações honestamente não faz

Limiar, calibração de SPL e geometria do array **não** são editáveis pelo
painel: vivem na configuração de cada nó, porque são por nó (uma via de tráfego
pesado tem piso de ruído diferente de uma rua residencial), e mudá-las
remotamente sem registro quebraria a reprodutibilidade da decisão.

E **não há botão de ligar a autuação**. O modo é declarado na configuração do
nó, exige instrumento certificado e base normativa federal que não existe hoje.
Apresentar um toggle aqui seria prometer o que o sistema não entrega — a tela
mostra o modo vigente e explica o bloqueio, com link para `docs/legal/inmetro.md`.

## Identidade visual

| Uso | Fonte |
|---|---|
| Títulos | Manrope |
| Interface | Inter |
| Dados técnicos (dB, timestamps, hashes) | JetBrains Mono |

| Cor | Hex | Uso |
|---|---|---|
| Âmbar | `#F5A623` | pendente — evita vermelho, que sugere culpa antes da validação |
| Verde | `#2ECC71` | confirmado |
| Laranja Studio Cerne | `#FF6B35` | assinatura de marca, com moderação |
| Base | escuro editorial | seriedade institucional |

## Detalhe que não é detalhe

Todo texto vindo da API é escapado antes de entrar no HTML — os campos passam
pelo nó e por observação de operador, e nenhum dos dois é lugar de confiar
cegamente. A mídia é buscada por `fetch` com o token e entregue como blob:
`<img>` e `<audio>` não enviam cabeçalho de autenticação, e assinar a URL
colocaria credencial no histórico do navegador e no log do servidor.
