# PROMPTS DE CONSTRUÇÃO — CLAUDE CODE
## Sistema de Fiscalização Sonora Inteligente (radar antibarulho)

Este documento reúne os prompts para construir o sistema no Claude Code, na ordem recomendada no manual técnico (seção 9.3). Cada prompt assume que os anteriores já foram executados — rode em sequência, um módulo por sessão, para manter o contexto de cada sessão pequeno e focado (eficiência de token).

**Como usar:** abra o Claude Code na pasta do projeto e cole o prompt correspondente à etapa em que você está. Ajuste trechos entre `[colchetes]` com informação específica sua antes de enviar.

---

## PROMPT 0 — Setup inicial do repositório

```
Quero criar um novo projeto chamado "radar-sonoro". É um sistema de fiscalização
sonora inteligente para detectar motocicletas com escapamento adulterado, localizar
a direção do som com um array de microfones, e acionar uma câmera para capturar a
placa como evidência.

Crie a estrutura de pastas abaixo, com um README.md em cada pasta explicando
brevemente o papel do módulo (ainda sem código, só a estrutura e documentação):

radar-sonoro/
├── edge/
│   ├── audio_capture/
│   ├── localization/
│   ├── classifier/
│   ├── camera_trigger/
│   └── evidence_packager/
├── vision/
│   ├── vehicle_type/
│   ├── plate_ocr/
│   └── trajectory/
├── backend/
│   ├── ingestion_api/
│   ├── review_queue/
│   ├── training_pipeline/
│   └── audit_log/
├── dashboard/
├── docs/
│   ├── legal/
│   └── field-notes/
└── infra/

Crie também um docs/DECISIONS.md com as decisões de arquitetura já tomadas, para
servir de memória do projeto entre sessões futuras:
- Hardware de borda: Raspberry Pi CM4 (não ESP32 — processamento insuficiente
  para localização direcional + classificação de áudio em tempo real)
- Localização direcional: técnica GCC-PHAT com array de 4-6 microfones MEMS I2S
  (ICS-43434)
- Classificação de assinatura acústica: modelo leve sobre espectrograma, não
  decisão por decibel puro
- Todo evento passa por validação humana antes de gerar multa ou virar dado de
  treino (nunca aprendizado automático sem confirmação)
- Sistema é produto independente, não integração com sistema interno da
  prefeitura — a prefeitura recebe acesso via dashboard/API/exportação
- Retenção de dado e uso para treino têm política própria (LGPD), documentada
  em docs/legal/
- Medição oficial de dB para fins legais vem de um sonômetro Classe 1
  certificado (IEC 61672, certificado RBC/Inmetro), integrado como componente
  separado — o array de microfones MEMS (ICS-43434) serve só para localização
  direcional e classificação de assinatura acústica, nunca como prova legal de
  decibel isoladamente (ver docs/legal/inmetro.md)
- O protocolo de comunicação do sonômetro varia por fabricante/modelo — a
  leitura do sonômetro deve ser isolada numa camada de adaptação própria
  (interface abstrata + implementação específica do modelo), para que trocar
  de sonômetro no futuro (ex: Classe 2 na validação → Classe 1 na produção)
  não exija alterar nenhum outro módulo do sistema
- O sistema opera em dois MODOS, configuráveis, não dois sistemas diferentes:
  `modo=triagem` (padrão atual — gera dados de priorização/mapa de calor para
  a prefeitura direcionar fiscalização humana, NÃO gera autuação) e
  `modo=autuacao` (desativado por padrão — só deve ser habilitado quando
  houver regulamentação federal confirmada que valide multa automática por
  ruído; ver docs/legal/inmetro.md). O pacote de evidência e a validação
  humana existem independente do modo — a diferença é só se o evento vira
  estatística de priorização ou rascunho de auto de infração

Use Python como linguagem principal para os módulos de processamento de sinal e
ML (bom suporte a bibliotecas de áudio/DSP), e defina isso no README raiz.
```

---

## PROMPT 1 — Captura de áudio (`edge/audio_capture`)

```
Estou no módulo edge/audio_capture do projeto radar-sonoro (veja docs/DECISIONS.md
para contexto de arquitetura).

IMPORTANTE: o array de microfones MEMS serve para localização direcional e
classificação de assinatura acústica — NÃO é a fonte da medição oficial de dB
para fins legais. A medição legal vem de um sonômetro comercial (Classe 1 ou 2,
conforme a fase do projeto) separado, integrado via USB/serial. Documente essa
distinção claramente no README do módulo.

Preciso de um script Python que:
1. Capture áudio simultâneo de 4 microfones MEMS I2S (ICS-43434) conectados a um
   Raspberry Pi CM4, com timestamps sincronizados entre os canais
2. Grave em buffer circular de 30 segundos, mantendo sempre os últimos 30s em
   memória (para poder recuperar o áudio de antes do pico de som quando um evento
   for detectado)
3. Calcule um nível de pressão sonora aproximado (SPL, em dB) em tempo real a
   partir do array MEMS — usado apenas para acionar o classificador e a
   localização, não como prova legal
4. Crie uma CAMADA DE ADAPTAÇÃO ISOLADA para a leitura do sonômetro comercial:
   - Uma interface abstrata `SonometroReader` com um método `ler_db()` que
     qualquer implementação específica de fabricante precisa seguir
   - Uma implementação mock/simulada, que devolve valores de teste, para eu
     poder desenvolver sem o hardware físico ainda
   - Documente claramente no README que, quando eu tiver o modelo exato do
     sonômetro comprado, a implementação real (ex: `SonometroXYZReader`) precisa
     ser escrita seguindo o protocolo específico daquele fabricante (vou
     fornecer o datasheet/manual do modelo quando tiver em mãos) — e que essa é
     a ÚNICA parte do sistema que muda se eu trocar de modelo de sonômetro
     no futuro (ex: Classe 2 de validação → Classe 1 de produção)
5. Exponha uma interface simples para os módulos seguintes (localization,
   classifier) consumirem o buffer de áudio + valor de SPL do array MEMS +
   valor de dB do sonômetro (via `SonometroReader`)

Ainda não tenho o hardware físico em mãos. Crie também um modo de simulação que lê
de arquivos .wav (4 canais) para eu poder testar a lógica sem o array de
microfones físico ainda.

Documente as bibliotecas Python necessárias em um requirements.txt.
```

---

## PROMPT 2 — Localização direcional (`edge/localization`)

```
Estou no módulo edge/localization do projeto radar-sonoro (veja docs/DECISIONS.md).

Preciso implementar localização direcional de fonte sonora usando GCC-PHAT
(Generalized Cross-Correlation with Phase Transform), a partir do áudio de 4
microfones capturado pelo módulo edge/audio_capture.

1. Implemente a função de GCC-PHAT para estimar a diferença de tempo de chegada
   (TDOA) entre pares de microfones
2. A partir das TDOAs, estime o ângulo de chegada do som (assumindo os 4
   microfones dispostos em círculo — deixe a geometria exata como parâmetro
   configurável, ainda não decidi o raio exato do array)
3. Retorne o ângulo estimado com uma margem de confiança/erro
4. Crie testes unitários com sinais sintéticos (som gerado artificialmente vindo
   de um ângulo conhecido) para validar que a estimativa bate com o ângulo
   esperado antes de eu testar com áudio real

Explique no README do módulo, em linguagem simples, como o algoritmo funciona —
vou precisar explicar isso para a prefeitura eventualmente e quero entender a
lógica, não só ter o código pronto.
```

---

## PROMPT 3 — Classificador de assinatura acústica (`edge/classifier`)

```
Estou no módulo edge/classifier do projeto radar-sonoro (veja docs/DECISIONS.md).

Quero um pipeline de classificação de áudio que distingue: escapamento de moto
adulterado vs. buzina vs. obra/construção vs. trovão vs. som ambiente normal.

1. Função para extrair espectrograma (mel-spectrogram) de um trecho de áudio
2. Arquitetura de modelo leve o suficiente para rodar em tempo real num Raspberry
   Pi CM4 (sugira uma arquitetura adequada — algo como uma CNN pequena sobre o
   espectrograma, não um modelo pesado)
3. Script de treino que aceita uma pasta de áudios rotulados por subpasta (uma
   subpasta por classe) e treina o modelo
4. Script de inferência que recebe um trecho de áudio e retorna a classe prevista
   + score de confiança
5. Ainda não tenho dados de treino reais. Crie um script auxiliar de "data
   augmentation" que pega áudio limpo (ex: gravações de escapamento gravadas de
   perto, sem ruído de fundo) e simula condição de rua: adiciona ruído de fundo
   urbano, reverberação, e atenuação por distância — para eu poder fazer um
   pré-treino com áudio da internet antes de ter gravação de campo própria

Documente claramente no README que esse pré-treino é provisório e que o modelo
precisa ser re-treinado com dado de campo real de Bauru assim que disponível —
não é a versão final.
```

---

## PROMPT 4 — Acionamento de câmera (`edge/camera_trigger`)

```
Estou no módulo edge/camera_trigger do projeto radar-sonoro (veja docs/DECISIONS.md).

Preciso de um script que:
1. Recebe como entrada: o score de confiança do classificador (edge/classifier) e
   o ângulo estimado (edge/localization)
2. Aciona a captura da câmera ANPR SOMENTE quando o score de confiança do
   classificador ultrapassar um limiar configurável (deixe o limiar como
   parâmetro, vou calibrar depois com dados reais)
3. Se o score for intermediário (nem alta confiança nem claramente descartável),
   registra o evento mas NÃO aciona a câmera automaticamente — só fica marcado
   como "ambíguo" para eventual revisão manual, conforme o princípio de
   verificado vs. inferido do projeto
4. Simule a interface de câmera por enquanto (não tenho o hardware ANPR ainda) —
   crie uma interface abstrata que o módulo real de captura vai implementar
   depois, e um mock que só salva um frame de um vídeo de teste local

Documente a lógica de decisão (quando aciona, quando não aciona, quando marca
como ambíguo) claramente no README, porque essa lógica é parte do argumento
jurídico do projeto (reduzir falso positivo).
```

---

## PROMPT 5 — Montagem do pacote de evidência (`edge/evidence_packager`)

```
Estou no módulo edge/evidence_packager do projeto radar-sonoro (veja
docs/DECISIONS.md).

Preciso de um script que monta o pacote de evidência de cada evento capturado,
contendo:
- Áudio bruto (10s antes/depois do pico, do buffer do audio_capture)
- Valor de SPL medido + referência da calibração usada
- Foto da placa + foto panorâmica (do camera_trigger)
- Ângulo de chegada estimado (do localization)
- Timestamp sincronizado (NTP) e geolocalização do sensor (fixa, configurável
  por nó)
- Score de confiança do classificador
- Um hash SHA-256 de todo o pacote, para garantir integridade (qualquer alteração
  posterior no pacote muda o hash, o que serve como prova de que não foi
  adulterado)

Estruture o pacote como um objeto JSON com os metadados + referências aos
arquivos de mídia (áudio/foto), e serialize tudo num único arquivo compactado por
evento, pronto para ser enviado ao backend.

Inclua testes que verificam que o hash muda se qualquer campo do pacote for
alterado depois de gerado.
```

---

## PROMPT 6 — API de ingestão (`backend/ingestion_api`)

```
Estou no módulo backend/ingestion_api do projeto radar-sonoro (veja
docs/DECISIONS.md).

Preciso de uma API (FastAPI) que:
1. Recebe pacotes de evidência enviados pelos nós de borda via HTTPS (formato
   definido em edge/evidence_packager)
2. Valida o hash do pacote recebido (rejeita se não bater, indicando corrupção
   ou adulteração em trânsito)
3. Armazena o pacote em um storage (comece com armazenamento local em disco,
   estruturado por data/nó, para eu poder trocar por object storage na nuvem
   depois sem redesenhar a lógica)
4. Registra a chegada do evento em uma fila de revisão (vamos construir
   backend/review_queue na próxima etapa — por enquanto, só grave num banco
   simples, tipo SQLite, com status "pendente_revisao")
5. Retorna confirmação de recebimento ao nó de borda

Use autenticação simples por token entre nó e API por enquanto (não é produção
ainda, é MVP).
```

---

## PROMPT 7 — Fila de revisão humana + dashboard (`backend/review_queue` + `dashboard`)

```
Estou construindo backend/review_queue e dashboard do projeto radar-sonoro (veja
docs/DECISIONS.md — todo evento precisa de validação humana antes de virar multa
ou dado de treino, isso é inegociável no desenho).

Preciso de:
1. Uma API simples que lista eventos com status "pendente_revisao" (do banco
   criado em backend/ingestion_api)
2. Um endpoint para o operador confirmar ou rejeitar um evento, com campo de
   observação opcional
3. Ao confirmar, o evento muda de status para "confirmado" (elegível para virar
   dado de treino depois) ou "confirmado_multa" se for gerar autuação
4. Ao rejeitar, muda para "rejeitado" (não vira multa nem dado de treino)
5. Um dashboard web simples (pode ser uma interface básica em React ou até HTML+
   JS simples) que mostra: lista de eventos pendentes, para cada evento o áudio
   (player), a foto da placa, o ângulo estimado, o score de confiança — e os
   botões de confirmar/rejeitar

Priorize funcionar bem localmente para eu testar com os dados do MVP antes de
pensar em deploy na nuvem.
```

---

## PROMPT 8 — Visão computacional (`vision/`)

```
Estou construindo os módulos vision/vehicle_type e vision/plate_ocr do projeto
radar-sonoro (veja docs/DECISIONS.md). Isso só entra depois que a parte de áudio
(edge/) já está validada — não construa isso antes da etapa de áudio funcionar.

1. vision/vehicle_type: classificador de imagem que confirma se o veículo no
   frame capturado é uma motocicleta (use um modelo pré-treinado leve, tipo
   MobileNet fine-tuned, não precisa treinar do zero)
2. vision/plate_ocr: reconhecimento de placa com dois modelos/pipelines de OCR
   independentes, retornando a leitura de cada um + uma flag de "concordância"
   (só aceita a leitura como confiável se os dois modelos concordarem)

Documente claramente que ambos os módulos são complementares ao áudio, não
substitutos — a decisão principal de "isso é uma infração" vem do áudio
(classifier + localization), a visão computacional só confirma e desambigua.
```

---

## PROMPT 9 — Pipeline de re-treino (`backend/training_pipeline`)

```
Estou construindo backend/training_pipeline do projeto radar-sonoro (veja
docs/DECISIONS.md). Isso só faz sentido depois que já tenho volume real de
eventos confirmados pelo operador humano (backend/review_queue).

Preciso de um pipeline que:
1. Busca todos os eventos com status "confirmado" desde o último re-treino
2. Combina esse dado novo com uma amostra fixa do dado de treino histórico (não
   substitui o dataset antigo — isso evita esquecimento catastrófico, conforme
   docs/DECISIONS.md)
3. Re-treina o modelo do edge/classifier com o dataset combinado
4. Antes de promover o modelo novo para produção, testa ele contra um conjunto
   de validação fixo e separado — só substitui o modelo em produção se a
   performance no conjunto de validação for igual ou melhor que o modelo atual
5. Registra em log cada ciclo de re-treino: quantos eventos novos entraram,
   performance antes/depois, se o modelo foi promovido ou não

Rode isso como um job em lote (não em tempo real) — sugira uma frequência
razoável (ex: semanal) e explique por quê no README.
```

---

## PROMPT 10 — Trilha de auditoria (`backend/audit_log`)

```
Estou construindo backend/audit_log do projeto radar-sonoro (veja
docs/DECISIONS.md).

Preciso de um log de auditoria imutável que registra:
- Cada evento recebido (ingestion_api)
- Cada ação de revisão humana (quem confirmou/rejeitou, quando, review_queue)
- Cada ciclo de re-treino do modelo (training_pipeline)
- Qualquer acesso ao pacote de evidência de um evento específico (quem acessou,
  quando)

Use uma estrutura de hash-chain (cada entrada de log inclui o hash da entrada
anterior) para que qualquer adulteração no histórico seja detectável — isso é
parte do argumento de robustez jurídica do projeto perante contestação de multa.

Documente no README como verificar a integridade da cadeia completa de logs.
```

---

## PROMPT 11 — Plataforma de gestão completa (`dashboard/` expandido)

```
Estou expandindo o dashboard do projeto radar-sonoro (veja docs/DECISIONS.md) de
um painel básico de revisão para a plataforma de gestão completa, chamada ECOAR.

O sistema opera hoje em `modo=triagem` (ver docs/DECISIONS.md) — a entrega
central para a prefeitura é priorização de fiscalização, não autuação. O
dashboard precisa deixar isso claro na hierarquia visual: a tela de
priorização é a primeira que o operador vê, não a fila de revisão.

Preciso adicionar, sobre a base já criada no Prompt 7:

1. Controle de acesso (RBAC simples): dois perfis, "operador" (revisa e confirma/
   rejeita eventos, consulta histórico, exporta relatório) e "admin" (tudo do
   operador + gestão de nós, versão de modelo, auditoria completa)
2. Tela de priorização (tela inicial/home do dashboard): mapa de calor dos
   pontos com mais eventos confirmados, cruzado por horário do dia e dia da
   semana — o entregável central em modo=triagem, pensado para o operador
   levar direto para a equipe de fiscalização humana decidir onde e quando
   fazer blitz
3. Tela de mapa de nós: lista/mapa dos sensores instalados, com status
   (online/offline), nível de bateria e timestamp da última captura
4. Tela de histórico: busca e filtro de eventos já confirmados/rejeitados (por
   data, local, status) — importante para recuperar evidência específica caso
   o sistema mude para modo=autuacao no futuro
5. Tela de métricas: gráficos de eventos por dia/local, taxa de falso positivo ao
   longo do tempo (eventos rejeitados / total), e um comparativo simples de custo
   estimado vs. fiscalização manual (blitz)
6. Tela de gestão de modelo: lista de versões do classificador (dado gerado pelo
   backend/training_pipeline), performance de cada versão no conjunto de
   validação, e botão para reverter para uma versão anterior
7. Tela de auditoria: visualização legível da cadeia de hash do backend/audit_log,
   com indicador visual claro se a cadeia está íntegra ou se algo foi alterado
8. Tela de configurações: limiar de confiança do classificador, calibração de SPL
   por sensor, política de retenção de dado (dias), gestão de usuário, e um
   toggle visível (só admin) para alternar entre modo=triagem e modo=autuacao
9. Botão de exportação: em modo=triagem, gera um relatório de priorização em
   PDF; em modo=autuacao, gera o pacote de evidência completo pronto para o
   sistema de autuação da prefeitura

Identidade visual do produto (nome: ECOAR):
- Tipografia de títulos: Manrope ou Space Grotesk
- Tipografia de corpo/interface: Inter
- Tipografia de dados técnicos (dB, timestamps, hashes): JetBrains Mono
- Cores funcionais: âmbar (#F5A623) para eventos pendentes, verde (#2ECC71) para
  confirmados, base escura editorial, laranja (#FF6B35) usado com moderação como
  cor de assinatura de marca

Mantenha a interface densa em informação mas legível — é uma ferramenta de uso
diário por operador municipal, não uma landing page.
```


---

## PROMPT 12 — Detecção de violação e proteção patrimonial (`edge/tamper_detection`)

```
Estou criando o módulo edge/tamper_detection do projeto radar-sonoro (veja
docs/DECISIONS.md). O objetivo é detectar tentativa de furto ou violação física
do nó instalado em via pública, e garantir que o alerta e a evidência saiam
ANTES do equipamento ser removido ou desligado.

Preciso de um módulo Python que:

1. Leia um acelerômetro/giroscópio MPU-6050 via I2C e detecte:
   - Impacto (pico de aceleração acima de limiar configurável)
   - Inclinação anômala (mudança sustentada de orientação em relação a uma
     posição de referência calibrada na instalação)
   - Movimento contínuo (equipamento sendo carregado/removido)
   Cada tipo com limiar próprio e configurável, para evitar falso positivo por
   vento, vibração de tráfego pesado ou poste sendo atingido levemente

2. Leia uma chave magnética (reed switch) em GPIO, detectando abertura da tampa
   do gabinete

3. Detecte queda da alimentação principal (transição para bateria de backup) e
   trate isso como evento de violação em potencial

4. Ao detectar QUALQUER um desses eventos, execute nesta ordem de prioridade
   (assumindo que o tempo de vida restante do equipamento pode ser de segundos):
   a) Dispare captura de imagem pela câmera (reutilize a interface do módulo
      edge/camera_trigger)
   b) Envie alerta imediato ao backend com tipo de evento, timestamp, ID do nó
      e a imagem — com prioridade máxima na fila de envio, à frente de qualquer
      pacote de evidência acústica pendente
   c) Registre o evento localmente também, para caso a transmissão falhe e o
      equipamento seja recuperado depois

5. Implemente um heartbeat: envio periódico (intervalo configurável) de sinal de
   vida ao backend, com status de bateria e saúde dos sensores. O backend deve
   poder identificar ausência de heartbeat como possível violação/falha

6. Tenha um "modo manutenção" que suspende os alertas temporariamente, acionado
   por autenticação, para a equipe poder abrir o gabinete legitimamente sem
   disparar alarme falso

Crie também um modo de simulação (sem hardware físico) que permita disparar
cada tipo de evento manualmente, para eu testar a cadeia completa de alerta
antes de ter o MPU-6050 e o reed switch em mãos.

No backend e no dashboard, os alertas de violação devem aparecer em canal
separado dos eventos acústicos — é ocorrência operacional/patrimonial, não
evento de fiscalização.

Documente as bibliotecas necessárias em requirements.txt.
```

---

## PROMPTS 13-16 — ROADMAP MODULAR (`docs/projeto/manual-tecnico.md` seção 12)

Estes quatro prompts correspondem aos módulos levantados na seção 12 do manual
técnico (roadmap além do ruído de escapamento). Depende de: 4-5 (câmera e
evidência) para os que reaproveitam a câmera; nenhum deles depende de 8 ou 9
(visão validada em campo / re-treino), porque nenhum reaproveita o classificador
de escapamento já treinado.

**Nível de prontidão é bem diferente entre os quatro** — não trate como um bloco
único:

- **13 (contagem de tráfego)** é o único pronto para construção direta: reaproveita
  hardware já instalado, não usa dado pessoal, modelo pré-treinado existe pronto.
- **14 (cruzamento com veículos furtados)** é viável tecnicamente, mas trava numa
  peça que não é código: acesso formal a uma base de segurança pública. O prompt
  constrói a abstração e o mock; a implementação real espera a decisão de negócio.
- **15 (colisão) e 16 (disparo de arma)** ainda não têm especificação técnica —
  os prompts abaixo são de **estudo de viabilidade**, não de construção. Rodar o
  estudo antes de abrir um prompt de build é a mesma lógica de "verificado vs.
  inferido" aplicada à própria decisão de construir.

---

## PROMPT 13 — Contagem e classificação de tráfego (`edge/traffic_counter`)

```
Estou criando o módulo edge/traffic_counter do projeto ECOAR (veja
docs/DECISIONS.md para contexto de arquitetura, e docs/projeto/manual-tecnico.md
seção 12.1).

Diferente do pipeline acústico (edge/camera_trigger), este módulo não espera um
evento de som: ele amostra a câmera ANPR já instalada em intervalo fixo,
independente de haver ou não escapamento adulterado passando.

Preciso de:
1. Um capturador de quadros com cadência configurável (ex.: 1-2 fps),
   reaproveitando a interface de câmera já definida em
   edge/camera_trigger/camera.py — não duplicar a abstração, estender se
   precisar de um método de captura contínua além do disparo por evento
2. Um classificador de tipo de veículo por quadro (moto/carro/ônibus/caminhão/
   nenhum), usando um modelo pré-treinado leve (ex.: um detector tipo
   YOLO-nano/MobileNet-SSD já treinado em classes de veículo comuns — não é
   preciso treinar do zero, ao contrário do classificador acústico de
   escapamento, que não tinha dataset público equivalente)
3. Agregação local por hora e tipo — o nó soma contagens, não guarda quadro a
   quadro nem envia imagem ao backend. Isso é deliberado: reduz banda 4G e não
   cria dado pessoal desnecessário — mesmo não sendo placa (D10 é sobre placa
   especificamente), o princípio de minimização de docs/legal/lgpd.md vale aqui
   também
4. Um endpoint novo de envio dos agregados (ex.: POST /v1/trafego, corpo com
   no_id, janela de tempo, contagem por tipo) — separado do pipeline de eventos
   acústicos, sem tocar na fila de revisão: este dado não precisa de validação
   humana individual, porque não gera multa nem estatística de priorização de
   ruído — é um dado operacional à parte
5. Modo de simulação sem câmera física: uma fonte de vídeo/quadros sintética ou
   de arquivo, no mesmo padrão de edge/audio_capture/sintetico.py, para eu
   testar sem hardware ainda (D11)
6. No dashboard, uma tela nova (ou uma seção dentro de Métricas) mostrando
   volume por tipo/hora/nó

Documente no README do módulo que a contagem é aproximada (limitação de
qualquer classificador de visão em condição real de rua, ângulo de câmera,
iluminação noturna) e que não tem qualquer finalidade de fiscalização — é dado
de planejamento de mobilidade, não evidência de infração.
```

---

## PROMPT 14 — Cruzamento com lista de veículos furtados/roubados (`vision/plate_ocr` + adaptador de consulta)

```
Estou implementando vision/plate_ocr e o cruzamento com lista de veículos
furtados/roubados do projeto ECOAR (veja docs/DECISIONS.md — D10 — e
docs/legal/lgpd.md antes de começar).

IMPORTANTE — isso é uma finalidade de tratamento de dado NOVA e DIFERENTE da
fiscalização de ruído: cruzamento de placa com base de segurança pública é
propósito de segurança, não de trânsito, e por LGPD (docs/legal/lgpd.md,
"finalidades distintas, retenções distintas") precisa de base legal, retenção e
trilha de auditoria PRÓPRIAS — não reaproveitar a trilha de evidência de ruído
para isso.

1. Implemente vision/plate_ocr: dois pipelines de OCR independentes sobre a
   mesma imagem de placa (já capturada pelo evidence_packager). A leitura só é
   aceita como confiável se os dois concordarem; divergência não vira decisão
   automática de nada
2. Crie uma interface abstrata BaseListaVeiculosFurtados com um método
   consultar(placa: str) -> ResultadoConsulta, seguindo o mesmo padrão de
   camada de adaptação isolada do SonometroReader (docs/DECISIONS.md D5) — uma
   implementação mock que devolve resultado de teste, para eu desenvolver sem
   acesso real à base de segurança pública ainda (que exige convênio formal e
   não é algo que o código resolve sozinho)
3. Trate o resultado da consulta com o mínimo de retenção possível: se não
   houver correspondência, a placa lida NÃO é persistida em lugar nenhum — nem
   em log, nem em métrica, nem em texto claro — o valor existe só durante o
   cálculo da consulta e é descartado depois. Isso segue a mesma regra do log
   de auditoria de ruído (nunca placa em texto claro), aplicada aqui com o
   mesmo rigor
4. Se houver correspondência (placa na lista de furtados/roubados), trate como
   canal de alerta separado, no mesmo padrão do canal de violação patrimonial
   já existente (docs/DECISIONS.md D14) — prioridade máxima, endpoint próprio,
   nunca misturado com a fila de revisão de ruído
5. Esse cruzamento só pode rodar quando um novo flag de configuração
   (ex.: seguranca.cruzamento_furto: habilitado) estiver explicitamente ligado,
   e a configuração precisa recusar subir (fail-closed, mesmo padrão do
   modo=autuacao em edge/config.py) se esse flag estiver ligado sem uma base
   normativa/convênio declarado
6. Documente claramente no README que a implementação real de
   BaseListaVeiculosFurtados (a consulta de verdade) depende de acesso formal a
   uma base de segurança pública (SINESP/Detran/Polícia Civil) que ainda não
   temos — o código fica pronto, o acesso ao dado é decisão de negócio, não
   técnica

Depois de construído, registre esta decisão em docs/DECISIONS.md (nova entrada
D15) e documente a finalidade/retenção nova em docs/legal/lgpd.md.
```

---

## PROMPT 15 — Detecção de acidente/colisão — estudo de viabilidade (não é prompt de construção)

```
Estou avaliando a viabilidade de um módulo de detecção de acidente/colisão para
o projeto ECOAR (veja docs/DECISIONS.md e docs/projeto/manual-tecnico.md seção
12.2 — este módulo ainda não tem especificação técnica, é direção futura).

Ainda NÃO é para construir o módulo de produção. Preciso de um estudo de
viabilidade:

1. Pesquise se existe dataset público de áudio rotulado com eventos de colisão/
   frenagem brusca/estilhaçamento (datasets de "urban sound event detection"
   costumam ter classes parecidas) — preciso saber se dá para começar de dado
   público antes de decidir se vale investir em captação própria (que aqui, ao
   contrário do escapamento, não posso gravar de forma segura e ética — não dá
   para provocar uma colisão real para treinar o modelo)
2. Com esse dataset (ou, na ausência dele, com sons sintéticos de teste —
   frenagem com pneu cantando + impacto), rode uma prova de conceito: o
   pipeline de extração de espectrograma já existente em edge/classifier
   (Prompt 3) consegue discriminar esse padrão (transiente curto e largo em
   frequência) do padrão de escapamento (tom sustentado com harmônicos)? Ou
   precisa de uma extração de feature diferente, sensível a transiente/onset,
   em vez do log-mel atual?
3. Avalie se o array de 4 microfones de um nó só (raio ~4,5 cm) é suficiente
   para essa tarefa, já que aqui a localização exata do veículo importa menos
   que "algo aconteceu perto deste poste, avise alguém rápido" — não precisa da
   mesma precisão angular que o escapamento
4. Me entregue um relatório curto (README do módulo) com: o que foi encontrado,
   se a discriminação parece viável com a arquitetura atual, o que faltaria
   para um MVP de teste real, e uma estimativa honesta de taxa de falso
   positivo esperada (buzina forte, motocicleta arrancando, trovão são
   candidatos óbvios a confundir)

Só depois desse estudo decido se abre um prompt de construção de verdade. Se a
resposta for "não dá para discriminar com confiança suficiente", quero que isso
fique registrado — não é fracasso, é a mesma lógica de "verificado vs. inferido"
aplicada à própria decisão de construir.

IMPORTANTE para qualquer versão futura deste módulo: nunca pode virar
"confirmação de acidente" — só um candidato para triagem humana imediata. O
sistema não substitui central de emergência nem verificação no local.
```

---

## PROMPT 16 — Detecção de disparo de arma de fogo — estudo de viabilidade (muda o escopo do produto)

```
Estou avaliando a viabilidade técnica de detecção de disparo de arma de fogo
sobre o hardware do ECOAR (veja docs/projeto/manual-tecnico.md seção 12.2 —
precedente citado: ShotSpotter/SoundThinking em Niterói).

ATENÇÃO — antes de qualquer código, isto muda o produto: o comprador não é mais
Secretaria de Trânsito/Mobilidade, é Segurança Pública/Guarda Municipal; a
decisão de acionamento tem consequência muito mais séria que uma multa
(resposta policial real); e a localização precisa pode exigir MULTILATERAÇÃO
ENTRE NÓS (vários sensores no mesmo bairro triangulando o mesmo disparo), não
só o array de um nó — isso é um módulo novo no backend, não uma extensão do
edge/localization atual.

Preciso, primeiro, só de um estudo técnico, sem compromisso de construção:

1. Levante os requisitos reais de sincronismo de relógio entre nós para
   multilateração funcionar (ShotSpotter usa GPS-disciplined time; o ECOAR hoje
   usa NTP comum para timestamp de evidência — que precisão isso dá, e é
   suficiente para triangular a que distância entre nós?)
2. Avalie se um MVP mais simples faz sentido antes de multilateração completa:
   cada nó reporta "ouvi um disparo, com esta confiança, neste horário", sem
   localização precisa — isso já teria valor operacional (volume e horário de
   ocorrência) por um custo de engenharia muito menor
3. Pesquise se existe dataset público de assinatura acústica de disparo
   (existem alguns usados em pesquisa acadêmica) para eu saber se dá pra
   prototipar um classificador antes de qualquer captação própria (que aqui é
   ainda mais inviável eticamente que colisão)
4. Me entregue um relatório de viabilidade com: precisão de timestamp
   necessária vs. disponível, dado de treino disponível, se o array de 4,5 cm
   de raio de um nó só discrimina disparo de outros transientes (rojão,
   escapamento estourando, porta batendo) com confiança mínima aceitável, e uma
   estimativa do escopo de engenharia adicional (multilateração é sistema
   novo, não ajuste)

Não escreva nenhum código de classificação ou decisão de acionamento ainda —
isto é levantamento, para eu decidir com informação se isso vira uma frente
nova (possivelmente produto separado, não módulo do ECOAR) ou fica só como
direção mencionada em reunião, como o manual já registra.
```

---

## ORDEM RESUMIDA

| # | Prompt | Depende de |
|---|---|---|
| 0 | Setup do repositório | — |
| 1 | Captura de áudio | 0 |
| 2 | Localização direcional | 1 |
| 3 | Classificador de assinatura acústica | 1 |
| 4 | Acionamento de câmera | 2, 3 |
| 5 | Pacote de evidência | 1, 2, 3, 4 |
| 6 | API de ingestão | 5 |
| 7 | Fila de revisão + dashboard | 6 |
| 8 | Visão computacional | 4 (validado em campo) |
| 9 | Pipeline de re-treino | 7 (com volume real de dado confirmado) |
| 10 | Trilha de auditoria | 6, 7 |
| 11 | Plataforma de gestão completa (ECOAR) | 7, 9, 10 |
| 12 | Detecção de violação / antifurto | 4, 6 |
| 13 | Contagem e classificação de tráfego | 4 |
| 14 | Cruzamento com veículos furtados/roubados | 5, 10 — e acesso formal a base externa (fora do código) |
| 15 | Detecção de acidente/colisão — **estudo de viabilidade** | 3 |
| 16 | Detecção de disparo de arma de fogo — **estudo de viabilidade** | 2, 3 |

---

*Cada prompt é ponto de partida, não roteiro fechado — ajuste conforme o Claude Code propuser alternativas técnicas ao longo da construção. O importante é manter o princípio de cada seção: validação humana antes de qualquer automação virar decisão final.*

*Prompts 15 e 16 são deliberadamente estudos, não construção: nenhum dos dois
tem especificação técnica validada (ver manual técnico seção 12.2), e o 16 muda
quem é o comprador do produto. Rodar o estudo primeiro é a mesma lógica de
"verificado vs. inferido" aplicada à decisão de construir, não só à decisão de
multar.*
