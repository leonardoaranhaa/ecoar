# edge/gunshot_detection — PROTÓTIPO CONCEITUAL, não capacidade validada

**Leia isto antes de usar qualquer parte deste módulo em reunião, proposta ou
demonstração apresentada como capacidade pronta.** Corresponde ao Nível 2 do
roadmap modular (`docs/projeto/manual-tecnico.md` seção 12.2) e ao Prompt 16
de `docs/projeto/prompts-claude-code.md` — um **estudo de viabilidade**, não
um módulo de produção.

## O que existe de verdade aqui

Um detector de transiente: encontra um pico de energia muito acima do piso de
ruído local da janela de áudio. Isso é DSP estabelecido (a mesma família de
técnica usada em detecção de onset em processamento de sinal) — funciona, é
testável, e não depende de nenhum dataset.

## O que NÃO existe

- **Nenhuma discriminação de assinatura.** O detector não sabe distinguir um
  disparo de um rojão, de um escapamento estourando, de uma porta batendo. Ele
  só sabe que "algo muito mais alto que o piso local aconteceu".
- **Nenhum dataset de treino.** Não há gravação de disparo real nem sintética
  validada — ao contrário do classificador de escapamento (que tem a cena de
  bancada como piso de segurança), aqui não existe piso nenhum além do
  detector de transiente puro.
- **Nenhuma localização precisa.** ShotSpotter e sistemas equivalentes
  triangulam a posição do disparo cruzando o horário de chegada em VÁRIOS
  sensores (multilateração entre nós). O ECOAR hoje só tem localização de nó
  único (`edge/localization`, GCC-PHAT), que estima ângulo, não posição
  absoluta — e o timestamp do nó usa NTP comum, não o sincronismo de precisão
  que multilateração exigiria.
- **Nenhuma integração com o orquestrador do nó.** `DetectorTransiente` não é
  chamado por `edge/no.py`. Isso é deliberado: religar isto ao laço principal
  do nó faria parecer que a cadeia de ponta a ponta está pronta, quando só o
  primeiro passo (detectar um pico) existe.

## Por que não chamar de "detecção de disparo"

Porque não é isso que o código faz. `CandidatoTransiente.tipo` é sempre
`candidato_transiente_nao_classificado` — nunca `disparo`. Todo resultado
carrega um campo `aviso` explícito. Isso é o mesmo princípio de "verificado vs.
inferido" que rege o resto do produto, aplicado à própria alegação de
capacidade: prometer detecção de arma de fogo sem base técnica seria o mesmo
erro que o projeto se recusa a cometer com autuação automática de ruído
(`CLAUDE.md`, regra de comunicação 1).

## Próximo passo real

Rodar o Prompt 16 (estudo de viabilidade) antes de qualquer construção
adicional: levantar dataset disponível, validar se a discriminação é possível
com a arquitetura atual, e dimensionar o que multilateração entre nós
exigiria. Só depois disso faz sentido decidir se este módulo vira produto — e,
se virar, é provável que mude o comprador (Segurança Pública/Guarda Municipal,
não Secretaria de Trânsito), o que também muda quem valida a demonstração.
