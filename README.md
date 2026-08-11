# ECOAR
### Ouve. Confirma. Prova.

Sistema de fiscalização sonora inteligente: identifica, localiza e registra
ocorrências de ruído veicular (escapamento adulterado) em via urbana, e entrega
à prefeitura um mapa de onde e quando o problema é mais crítico — para
direcionar a fiscalização humana que já existe.

**Studio Cerne** · Bauru/SP

---

## O que o sistema faz — e o que não faz

**Faz:** priorização de fiscalização, inteligência operacional, evidência
auditável com validação humana obrigatória.

**Não faz:** autuação automática. Não existe hoje no Brasil regulamentação
federal (Inmetro/CONTRAN) que valide multa automática por ruído veicular. A
arquitetura já contempla esse modo, mas ele permanece **desativado** até haver
base legal — ver `docs/legal/inmetro.md`.

## Como o sistema está organizado

```
ecoar/
├── edge/                    # roda no no de campo (Raspberry Pi CM4, no poste)
│   ├── audio_capture/       # array de 4 microfones MEMS I2S + buffer + SPL + sonometro
│   ├── localization/        # GCC-PHAT: de que direcao veio o som
│   ├── classifier/          # que som foi esse (escapamento? buzina? obra?)
│   ├── camera_trigger/      # decide se aciona a camera, e aciona
│   ├── evidence_packager/   # monta o pacote assinado do evento
│   ├── tamper_detection/    # antifurto: violacao do gabinete e do poste
│   └── uplink/              # fila persistente e envio ao backend via 4G
│
├── vision/                  # visao computacional (backend, fase posterior)
│   ├── vehicle_type/        # confirma que o veiculo e uma motocicleta
│   ├── plate_ocr/           # leitura de placa com dois OCR independentes
│   └── trajectory/          # desambigua trafego simultaneo
│
├── backend/                 # nuvem: recebe, guarda, organiza a revisao
│   ├── ingestion_api/       # recebe pacotes dos nos e valida hash
│   ├── review_queue/        # fila de eventos aguardando validacao humana
│   ├── training_pipeline/   # re-treino em lote com dado confirmado
│   └── audit_log/           # trilha de auditoria encadeada por hash
│
├── dashboard/               # painel do operador municipal
├── docs/                    # decisoes, base legal, notas de campo, hardware
├── config/                  # configuracao por no
├── scripts/                 # utilitarios de bancada e simulacao
└── tests/                   # suite automatizada
```

## Linguagem e stack

**Python** é a linguagem principal de todos os módulos de processamento de
sinal, ML e backend — é onde está o ferramental maduro de áudio/DSP
(`numpy`, `librosa`-equivalentes, `torch`). O dashboard é HTML+CSS+JS servido
pelo próprio backend, sem etapa de build.

| Camada | Escolha |
|---|---|
| Nó de campo | Python 3.11 em Raspberry Pi OS Lite 64-bit |
| Processamento de sinal | numpy (FFT, GCC-PHAT, log-mel — sem dependência pesada) |
| Classificador | baseline determinístico + CNN pequena opcional (torch) |
| Backend | FastAPI + SQLite no MVP (acesso isolado em `backend/db.py`) |
| Dashboard | HTML + CSS + JS, sem build |

## Rodar sem nenhum hardware

Todo periférico está atrás de uma interface com implementação simulada
(decisão D11 em `docs/DECISIONS.md`). O sistema inteiro roda numa máquina
comum:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest

# captura de bancada com cena sintética, sem microfone nenhum
python -m edge.audio_capture.main --fonte sintetica --azimute 90 --duracao 6
```

No nó de campo, a instalação adiciona os drivers reais:

```bash
pip install -r requirements-hardware.txt
```

## Estado da construção

Construção por etapas, conforme `01-tecnico/prompts-claude-code.md` do projeto.

| # | Etapa | Estado |
|---|---|---|
| 0 | Estrutura do repositório e decisões | **feito** |
| 1 | `edge/audio_capture` | **feito** |
| 2 | `edge/localization` | **feito** |
| 3 | `edge/classifier` | **feito** |
| 4 | `edge/camera_trigger` | **feito** |
| 5 | `edge/evidence_packager` | **feito** |
| 6 | `backend/ingestion_api` | **feito** |
| 7 | `backend/review_queue` + `dashboard` | **feito** |
| 8 | `vision/` | pendente |
| 9 | `backend/training_pipeline` | pendente |
| 10 | `backend/audit_log` | **feito** |
| 11 | Plataforma de gestão completa | **feito** |
| 12 | `edge/tamper_detection` | **feito** |

## Antes de mexer no código

Ler `docs/DECISIONS.md`. São 14 decisões de arquitetura já tomadas; várias delas
existem por razão jurídica, não técnica, e mudar sem registrar quebra o
argumento de conformidade do produto.
