# DECISÕES DE ARQUITETURA — ECOAR

Memória do projeto entre sessões. Cada decisão aqui já foi tomada e está
implementada no código. Mudança de qualquer uma delas exige registro nesta
página, não alteração silenciosa.

---

## D1 — Dois modos de operação, não dois sistemas

`modo=triagem` (padrão, único ativo hoje): o evento validado vira estatística de
priorização — mapa de calor de onde e quando o problema é pior, para a
prefeitura direcionar a fiscalização humana que já existe. **Não gera
autuação.**

`modo=autuacao` (desativado): o evento validado vira rascunho de auto de
infração. Só pode ser habilitado quando houver regulamentação federal
(Inmetro/CONTRAN) que valide multa automática por ruído veicular — ver
`docs/legal/inmetro.md`.

O pacote de evidência e a validação humana existem **independente do modo**. A
diferença é apenas o destino do evento confirmado.

**Implementação:** `edge/config.py` recusa carregar `modo=autuacao` sem o bloco
`autuacao:` preenchido (quem habilitou, base normativa, instrumento certificado
declarado). Fail-closed: erro de configuração cai para triagem ou aborta, nunca
para autuação.

## D2 — Validação humana obrigatória em todo evento, em qualquer modo

Nenhum evento vira dado de priorização, dado de treino ou rascunho de autuação
sem passar por um operador. O status inicial de todo evento ingerido é
`pendente_revisao`. Não existe caminho de código que pule essa etapa.

## D3 — Array MEMS ≠ medição legal

O array de 4 microfones SPH0645LM4H (substituto direto do ICS-43434, descontinuado
em 2026 — mesmo pinout) serve para **localização direcional** e
**classificação de assinatura acústica**. O SPL calculado a partir dele é
estimativa relativa, calibrada por campanha, marcada em todo lugar como
`valor_legal: false`.

Medição com validade legal exige instrumento certificado IEC 61672 Classe 1,
necessário apenas em `modo=autuacao`.

## D4 — Instrumento de medição é estação permanente (NMT), não sonômetro portátil

O produto pressupõe operação remota, sem operador em campo. Sonômetro de tripé
foi descartado. A integração com a NMT é **de dados** (rede ou porta digital),
nunca mecânica — abrir o invólucro do instrumento invalida a certificação.

## D5 — Camada de adaptação isolada para o instrumento de medição

`edge/audio_capture/sonometro.py` define a interface `SonometroReader`. Trocar
de modelo de instrumento (Classe 2 de validação → Classe 1 de produção) altera
**apenas** uma classe nesse arquivo. Nenhum outro módulo conhece o protocolo do
fabricante.

## D6 — Classificador de assinatura acústica, não limiar de decibel

Decisão por dB puro dispara com buzina, obra e trovão. O ECOAR extrai log-mel do
trecho e classifica a assinatura antes de acionar a câmera. O SPL é apenas
pré-gatilho barato: ele decide se vale a pena classificar, nunca se houve
infração.

## D7 — Decisão de acionamento é determinística e versionada

`edge/camera_trigger/decisao.py` é uma tabela de regras explícita, com versão de
política registrada em cada evento. Mesma entrada + mesma versão de política =
mesma saída, sempre. Três saídas possíveis: `acionar`, `ambiguo`, `descartar`.
Score intermediário registra o evento mas **não aciona a câmera** — é o
"verificado vs. inferido" aplicado a áudio.

## D8 — Fail-closed

Classificador indisponível, sonômetro exigido e ausente, geometria de array
inconsistente: o sistema não aciona a câmera e não descarta em silêncio. Ele
registra o evento como `ambiguo` com motivo explícito, ou recusa iniciar. Nunca
assume que "provavelmente estava tudo bem".

## D9 — Cadeia de custódia desde a captura

Cada pacote de evidência carrega SHA-256 de cada arquivo de mídia mais um hash
do manifesto canônico. O backend revalida o hash na ingestão e rejeita pacote
que não bate. A trilha de auditoria é hash-chain: cada entrada inclui o hash da
anterior.

## D10 — Nenhuma leitura de placa no nó de borda

O nó captura a imagem e a envia. OCR de placa (`vision/plate_ocr`) roda no
backend, depois da triagem, e só quando o modo exigir. Em `modo=triagem` a placa
não é lida nem armazenada em texto: priorização não precisa saber qual veículo
era. Minimização de dado pessoal por desenho — ver `docs/legal/lgpd.md`.

## D11 — Hardware sempre atrás de uma interface, com implementação simulada

Todo periférico (array I2S, sonômetro, câmera, acelerômetro, reed switch) tem
uma classe abstrata e pelo menos duas implementações: a real e a simulada. As
bibliotecas de hardware (`sounddevice`, `smbus2`, `gpiozero`, `serial`, `cv2`)
são importadas **dentro** do driver, nunca no topo do módulo. Consequência: a
suíte de testes e o pipeline inteiro rodam numa máquina comum, sem nenhum
componente físico.

## D12 — Python no nó e no backend

Processamento de sinal e ML têm o melhor ferramental em Python. O backend é
FastAPI + SQLite no MVP, com o acesso a dados isolado em `backend/db.py` para
trocar por Postgres sem redesenhar a lógica. O dashboard é HTML+CSS+JS servido
pelo próprio backend — sem build, sem dependência de node no piloto.

## D13 — Aprendizado só com dado confirmado por humano

Re-treino em lote, nunca em tempo real. Dataset novo é sempre mistura de dado
confirmado recente + amostra fixa do histórico (evita esquecimento
catastrófico). Modelo novo só entra em produção se não piorar no conjunto de
validação fixo.

## D14 — Alerta de violação patrimonial é canal separado

Furto e violação de gabinete são ocorrência operacional, não evento de
fiscalização. Trafegam em endpoint próprio, com prioridade máxima na fila de
uplink (à frente de qualquer pacote acústico pendente) e aparecem em tela
separada no dashboard.

## D15 — Contagem de tráfego é dado operacional, sem placa, sem fila de revisão

`edge/traffic_counter` reaproveita a câmera já instalada, mas roda em
paralelo ao pipeline acústico — amostra em cadência fixa, não por evento de
som. Não lê placa (isso continua sendo só `vision/plate_ocr`, D10) e não
guarda quadro a quadro: o que sai do nó é contagem agregada por dia/hora/tipo
de veículo (`backend.registrar_trafego`, upsert que soma, nunca substitui).

Não passa pela fila de revisão (D2 não se aplica: não há decisão de infração
para validar) nem entra na priorização de fiscalização de ruído — é dado de
planejamento de mobilidade, em `GET /v1/trafego`, canal e tabela próprios
(`trafego_agregado`).

Desligado por padrão (`trafego.habilitado: false`). O classificador de tipo de
veículo é simulado (D11) até um modelo pré-treinado real ser integrado —
diferente do classificador acústico de escapamento, aqui existe modelo público
disponível, então o próximo passo é integração, não treino do zero.

## D16 — Detecção de disparo de arma de fogo é protótipo conceitual, não capacidade validada

`edge/gunshot_detection` implementa só um detector de transiente: um pico de
energia muito acima do piso de ruído local da janela — DSP estabelecido, sem
depender de dataset. Ele **não** discrimina disparo de outros transientes
urbanos (rojão, escapamento estourando, porta batendo), e essa discriminação
não está validada nem tem dataset de treino disponível. Localização precisa
exigiria multilateração entre nós (sistema novo, não extensão de
`edge/localization`) e sincronismo de relógio de precisão que o nó não tem
hoje (usa NTP comum).

Por isso:

- A saída nunca se chama "disparo": é sempre
  `candidato_transiente_nao_classificado`, com um campo `aviso` explícito em
  todo resultado e evento de auditoria (`ALERTA_DISPARO_CONCEITO` — o próprio
  nome da constante carrega "não validado").
- `disparo.habilitado` nasce `false` — liga só por decisão explícita.
- Canal separado (D14) tanto dos eventos acústicos quanto de violação
  patrimonial: `POST /v1/alertas-disparo-conceito`, tabela
  `alertas_disparo_conceito`.
- `DetectorTransiente` não está integrado ao orquestrador do nó
  (`edge/no.py`) — ligar isso ao laço principal faria parecer que a cadeia de
  ponta a ponta está pronta, quando só o primeiro passo existe.
- No dashboard, a tela carrega o rótulo "CONCEITO — NÃO VALIDADO" e só
  aparece mediante acionamento explícito (toggle em Configurações, admin),
  nunca visível por padrão.

Ver `docs/projeto/prompts-claude-code.md` Prompt 16 (estudo de viabilidade) e
`docs/projeto/manual-tecnico.md` seção 12.2 antes de tratar isso como
capacidade real em qualquer conversa comercial. Prometer detecção de disparo
sem essa base seria o mesmo erro que o projeto se recusa a cometer com
autuação automática de ruído (`CLAUDE.md`, regra de comunicação 1) — e aqui o
custo de errar é maior: uma resposta policial real, não uma multa.
