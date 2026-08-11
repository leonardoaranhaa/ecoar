# ECOAR

Sistema de fiscalização sonora inteligente. Sensores acústicos em poste que
identificam, localizam e registram ocorrências de ruído veicular, e entregam à
prefeitura um mapa de onde e quando o problema é pior — para direcionar a
fiscalização humana que já existe.

**Studio Cerne** · Bauru/SP

## O que é o produto (e o que não é)

O sensor não é o produto. O classificador não é o produto.

O produto é a **evidência que resiste a contestação**: cadeia de custódia,
validação humana registrada, trilha auditável, e o dado de priorização que
economiza blitz.

O ECOAR **não faz autuação automática**. Não existe regulamentação federal
(Inmetro/CONTRAN) que valide multa automática por ruído veicular no Brasil. A
arquitetura contempla esse modo e ele está desligado.

## Regras de arquitetura — inegociáveis

1. **VALIDAÇÃO HUMANA EM TODO EVENTO, EM QUALQUER MODO.** Nenhum evento vira
   estatística de priorização, dado de treino ou rascunho de autuação sem passar
   por um operador. Não existe caminho de código que pule isso.

2. **DECISÃO DE ACIONAMENTO É DETERMINÍSTICA E VERSIONADA.** Tabela de regras
   explícita, versão de política gravada em cada evento. Mesma entrada + mesma
   versão = mesma saída, sempre. Nunca usar modelo de linguagem para decidir se
   houve infração.

3. **FAIL-CLOSED.** Subsistema indisponível gera `ambiguo` com motivo explícito
   — nunca `descartar` em silêncio, nunca `acionar` por precaução. Configuração
   inválida aborta a inicialização.

4. **ARRAY MEMS ≠ MEDIÇÃO LEGAL.** O array faz localização e classificação. Todo
   valor de SPL que sai dele carrega `valor_legal: false`. Medição com validade
   legal exige instrumento certificado IEC 61672, necessário só em
   `modo=autuacao`.

5. **NENHUMA LEITURA DE PLACA NO NÓ.** Em `modo=triagem` a placa não é lida nem
   armazenada em texto. Priorização responde "onde e quando", não "quem".

6. **LOG NUNCA REGISTRA CONTEÚDO DE PLACA.** Registra que um evento ocorreu, o
   score, o ângulo, o identificador. Nunca a identificação do veículo. Sem
   exceção, nem em desenvolvimento.

7. **HARDWARE SEMPRE ATRÁS DE INTERFACE, COM IMPLEMENTAÇÃO SIMULADA.**
   Bibliotecas de hardware (`sounddevice`, `serial`, `smbus2`, `gpiozero`,
   `cv2`) são importadas dentro do driver, nunca no topo do módulo. A suíte
   inteira roda sem nenhum componente físico.

8. **CADEIA DE CUSTÓDIA DESDE A CAPTURA.** Hash no pacote desde o nó, revalidado
   na ingestão, trilha de auditoria encadeada. Não é remendo posterior.

9. **APRENDIZADO SÓ COM DADO CONFIRMADO POR HUMANO.** Re-treino em lote, dataset
   sempre misturado com histórico, promoção só se não piorar no conjunto de
   validação fixo.

## Regras de comunicação — inegociáveis

Valem para site, proposta, reunião, contrato e interface.

1. **NUNCA PROMETER AUTUAÇÃO AUTOMÁTICA.** O que se vende hoje é triagem e
   priorização. Prometer multa é vender o que não existe base legal para
   entregar.

2. **NUNCA CHAMAR O ARRAY DE "MEDIÇÃO CERTIFICADA".** São coisas diferentes, e
   confundir as duas em material público destrói a credibilidade técnica na
   primeira pergunta de um engenheiro da prefeitura.

3. **NUNCA DIZER "O EQUIPAMENTO CARO NUNCA FICA NO POSTE"** como se valesse
   sempre. É verdade no piloto; na operação contratada o instrumento é
   permanente e vem com seguro previsto em contrato. A formulação honesta está
   em `docs/hardware/README.md`.

4. **NUNCA USAR URGÊNCIA FABRICADA** nem superlativo vazio.

## Stack

- Nó de campo: Python 3.11 em Raspberry Pi CM4, Raspberry Pi OS Lite 64-bit
- Processamento de sinal: numpy (FFT, GCC-PHAT, log-mel) — sem dependência pesada
- Classificador: baseline determinístico + CNN pequena opcional (torch)
- Backend: FastAPI + SQLite no MVP, acesso isolado em `backend/db.py`
- Dashboard: HTML + CSS + JS, sem build
- Hospedagem: território nacional

## Convenções

- Português nos nomes de domínio de negócio (`evento`, `revisao`, `priorizacao`,
  `violacao`), inglês em código de infraestrutura
- Sem comentário óbvio; comentário só onde a razão não é evidente
- Todo módulo do caminho de decisão tem teste
- Migrations versionadas, nunca alteração manual de schema

## O que NÃO construir sem eu pedir

- Autenticação social / OAuth
- Sistema de billing
- Aplicativo móvel
- Integração profunda com sistema interno de prefeitura (exportação basta)
- Streaming de áudio ao vivo para o backend
- Reconhecimento facial, em qualquer forma

## Documentos de referência

Antes de trabalhar em algo, ler o documento da área.

| Área | Arquivo |
|---|---|
| Decisões de arquitetura | `docs/DECISIONS.md` |
| Base legal da medição | `docs/legal/inmetro.md` |
| LGPD, retenção, minimização | `docs/legal/lgpd.md` |
| Montagem e integração física | `docs/hardware/README.md` |
| Notas de campo | `docs/field-notes/` |

## Status atual

**Fase:** construção do MVP, modo=triagem. Etapa 0 (estrutura e decisões)
concluída; módulos de código ainda não começaram — ver a tabela de estado no
`README.md`.

**Hardware:** não adquirido. Todo o desenvolvimento acontece em modo de
simulação até os componentes chegarem, e a suíte de testes precisa continuar
passando sem hardware mesmo depois disso.

**Próximo passo lógico:** `edge/audio_capture` — buffer circular, SPL estimado e
a camada de adaptação do instrumento de medição.

**Pendência que não depende de código:** gravar áudio de campo nos pontos
críticos de Bauru antes de comprar hardware. É o teste mais barato da pergunta
mais arriscada do projeto.
