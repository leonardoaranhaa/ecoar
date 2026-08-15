# 📘 MANUAL TÉCNICO — SISTEMA DE FISCALIZAÇÃO SONORA INTELIGENTE — ECOAR
## Detecção acústica direcional + captura fotográfica automatizada para infração de escapamento adulterado
### Versão 1.1 | Agosto 2026 | Aplicação-alvo: Bauru/SP e região

---

## 0. POSICIONAMENTO ATUAL (leia antes do resto do documento)

Uma pesquisa de mercado aprofundada (ago/2026) confirmou que **não existe hoje
regulamentação federal (Inmetro/CONTRAN) que valide juridicamente multa
automática por ruído veicular no Brasil** — nem o sistema pioneiro de São José
dos Campos confirmou emissão de multa válida até o momento; Curitiba testou
sistema semelhante desde 2022 e nunca multou.

**Isso não invalida a arquitetura técnica abaixo — muda o que se promete a uma
prefeitura agora.** O sistema continua sendo construído exatamente como
descrito (classificador, localização, câmera, evidência com validação
humana), mas o produto vendido *hoje* é uma **ferramenta de triagem e
priorização de fiscalização** (mapas de calor de onde/quando o problema é
pior, para guiar operação humana), não autuação automática. Quando a
regulamentação avançar, o mesmo sistema já está pronto para o modo punitivo,
sem precisar ser reconstruído. Ver `radar-antibarulho-argumento-venda.md` para
o argumento de venda atualizado com esse posicionamento.

---

## 1. VISÃO GERAL

O sistema detecta veículos (principalmente motocicletas) com nível sonoro acima do limite legal, localiza a direção da fonte do som usando um array de microfones, aciona uma câmera para capturar a placa, e monta um pacote de evidência auditável — som + imagem + metadado — pronto para virar auto de infração com o mínimo de contestação possível.

**Diferença central em relação ao sistema já testado em São José dos Campos e Curitiba:** em vez de acionar a câmera só por limite de decibéis (o que gera falso positivo com buzina, obra, trovão), o sistema classifica a **assinatura acústica específica** de escapamento adulterado antes de acionar a câmera — e todo evento passa por validação humana antes de virar dado de priorização ou (futuramente, quando a regulamentação permitir) multa, o que reduz risco jurídico. Nenhum dos dois sistemas de referência confirmou emissão de multa válida até agosto/2026 — ver seção 0.

### Especificações-alvo

| Parâmetro | Especificação |
|---|---|
| Alcance de detecção direcional | até 15 m |
| Precisão de localização angular | ±5° |
| Limite legal de referência | 80 dB a 7 m (Res. 418/09 Conama) |
| Falso positivo (meta) | < 5% dos eventos capturados |
| Conectividade | 4G/LTE (Bauru tem cobertura consolidada, dispensa NB-IoT) |
| Alimentação | Rede elétrica pública (poste) + bateria de backup |
| Validação de evidência | Humana, antes de qualquer emissão de multa |

---

## 2. ARQUITETURA DO SISTEMA

```
┌───────────────────────────────────────────────────────────────┐
│                       NÓ DE BORDA (por poste)                  │
│  ┌─────────────────────────────────────────────┐               │
│  │  Array de 4-6 microfones MEMS (círculo)      │               │
│  │  SPH0645LM4H (I2S, resposta plana, baixo ruído)│              │
│  └──────────────────┬────────────────────────────┘             │
│                      ▼                                          │
│  ┌─────────────────────────────────────────────┐               │
│  │  Raspberry Pi CM5 (ou CM4) / Jetson Orin Nano│               │
│  │  - Medição de SPL (nível de pressão sonora)  │               │
│  │  - Localização direcional (GCC-PHAT)         │               │
│  │  - Classificador de assinatura acústica (ML) │               │
│  └──────────────────┬────────────────────────────┘             │
│                      ▼ (se disparo confirmado)                 │
│  ┌─────────────────────────────────────────────┐               │
│  │  Câmera ANPR (leitura de placa) + foto geral │               │
│  └──────────────────┬────────────────────────────┘             │
│                      ▼                                          │
│  ┌─────────────────────────────────────────────┐               │
│  │  Módulo 4G/LTE — envia pacote de evidência   │               │
│  └──────────────────┬────────────────────────────┘             │
└───────────────────────┼──────────────────────────────────────┘
                         ▼ HTTPS/MQTT (TLS)
┌───────────────────────────────────────────────────────────────┐
│                        BACKEND / NUVEM                          │
│  ┌────────────┐  ┌────────────────┐  ┌─────────────────────┐  │
│  │  Ingestão  │→ │  Fila de       │→ │  Painel de validação │  │
│  │  + hash de │  │  revisão humana│  │  (operador confirma  │  │
│  │  evidência │  │                │  │  ou descarta)         │  │
│  └────────────┘  └────────────────┘  └──────────┬───────────┘  │
│                                                   ▼              │
│                                       ┌──────────────────────┐ │
│                                       │  Geração de auto de   │ │
│                                       │  infração (integração │ │
│                                       │  com sistema municipal)│ │
│                                       └──────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. POR QUE ESSE HARDWARE (nível de processamento necessário)

Um microcontrolador simples (linha ESP32) não é suficiente aqui — **localizar a direção do som com múltiplos microfones e classificar o padrão acústico em tempo real exige poder de processamento que esse tipo de chip não tem.** Por isso o núcleo de borda é um computador de placa única: Raspberry Pi CM5/CM4 (mais barato, ~R$450-550) ou Jetson Orin Nano (mais caro, ~R$1.800, mas roda o classificador de ML localmente com folga).

**Recomendação para o MVP: Raspberry Pi CM5, com CM4 como alternativa equivalente.** A CM5 (lançada em nov/2024) é hoje a recomendação padrão para projeto novo — mesmo formato físico da CM4, processador mais rápido, preço na mesma faixa. A CM4 continua em produção garantida e é intercambiável na maioria dos casos, então qualquer uma resolve o MVP. Ambas são suficientes para o algoritmo de localização direcional e um classificador de áudio leve (rede neural pequena, tipo MobileNet adaptada para espectrograma). Jetson só se o classificador de imagem (ANPR) também rodar localmente em vez de na nuvem.

**Nota de manutenção da lista de componentes:** componentes eletrônicos têm ciclo de vida curto (12-18 meses até serem descontinuados). Antes de qualquer compra em volume, reconfirme disponibilidade dos itens da seção 11 — um item já foi descontinuado desde a primeira versão deste manual (ver nota na lista de materiais).

---

## 4. LOCALIZAÇÃO DIRECIONAL DO SOM (a parte que faz o "aponta pro veículo certo")

Esse é o componente que faz o sistema funcionar de verdade — sem ele, você só sabe que "algo bateu 80 dB", não qual veículo.

**Técnica: GCC-PHAT (Generalized Cross-Correlation with Phase Transform)**

1. Cada microfone do array capta o mesmo som com uma pequena diferença de tempo de chegada (alguns milissegundos), dependendo da posição da fonte.
2. O algoritmo calcula a correlação cruzada entre pares de microfones para estimar essa diferença de tempo (TDOA — time difference of arrival).
3. Com 4+ microfones dispostos em círculo, a triangulação das diferenças de tempo estima o ângulo de chegada do som com precisão de poucos graus.
4. Esse ângulo é usado para posicionar a câmera ANPR (fixa, com campo de visão amplo, ou motorizada com pan) na direção certa antes de disparar a foto.

Isso é matemática bem estabelecida (usada em assistentes de voz tipo Alexa/Google Home para saber de onde vem a fala) — não é experimental, é engenharia madura aplicada a um problema novo.

---

## 5. CLASSIFICADOR DE ASSINATURA ACÚSTICA (o anti-falso-positivo)

**Problema que resolve:** o sistema de São José dos Campos aciona por decibel puro — uma buzina forte, uma britadeira, ou até um trovão pode ativar a câmera à toa, gerando gasto de processamento e possível base fraca para contestação.

**Abordagem:**
1. Extrair espectrograma do som captado (representação tempo-frequência)
2. Classificador treinado para distinguir: escapamento de moto adulterado vs. buzina vs. obra vs. trovão vs. som ambiente normal
3. Como não existe dataset público brasileiro pronto para isso, o treinamento inicial precisa ser feito com gravações de campo — é viável gravar amostras reais em Bauru mesmo (ruas com reclamação recorrente, tipo Ponte São João, citada nas notícias locais) e rotular manualmente antes do MVP
4. **Aqui entra diretamente o seu framework de confiança:** cada evento carrega um score — "alta confiança de escapamento adulterado" (aciona câmera automaticamente) vs. "padrão ambíguo" (registra mas não aciona sozinho, fica para revisão) — isso é o "verificado vs. inferido" aplicado a áudio

---

## 6. PACOTE DE EVIDÊNCIA E CADEIA DE CUSTÓDIA

Esse é o ponto que o pioneiro de SJC está tropeçando (contestação judicial por falta de regulamentação). Resolver isso bem é o seu diferencial de venda.

Cada evento gerado grava, em um pacote único e assinado digitalmente (hash SHA-256):

- Áudio bruto (10 segundos antes/depois do pico)
- Medição de SPL calibrada, com certificado de calibração do sensor referenciado
- Foto da placa (ANPR) + foto panorâmica do momento
- Ângulo de chegada estimado (prova de que o som veio daquele veículo específico, não de outro na via)
- Timestamp sincronizado (NTP) e geolocalização do sensor
- Score de confiança do classificador
- Identificação do operador que validou (revisão humana obrigatória antes de gerar multa)

Isso vira o argumento central da proposta: **"não é só uma câmera que dispara sozinha — é um sistema com trilha auditável desde a captura até a validação humana, desenhado para resistir a recurso."**

---

## 7. INTEGRAÇÃO LEGAL — O QUE PRECISA SER RESOLVIDO ANTES DO PILOTO

- **Certificação Inmetro do sensor de SPL** — sem isso, a medição de decibéis não tem valor legal de prova (é o mesmo requisito que está travando SJC agora). Detalhamento e estratégia de vantagem abaixo (7.1).

### 7.1 Instrumento de medição certificado — categoria correta e estratégia

**Exigência técnica real:** o instrumento usado para medição de decibel com
valor legal precisa atender à norma IEC 61672 (todas as partes) — Classe 1, com
certificação e rastreabilidade metrológica. O array de microfones MEMS próprio
do projeto (seção 3-4) serve para localização direcional e classificação de
assinatura acústica, mas não substitui o instrumento certificado como medição
oficial — são propósitos diferentes.

**CATEGORIA CORRETA DE PRODUTO (correção importante)**

Existem duas categorias distintas no mercado, e escolher a errada inviabiliza o
projeto:

| | Sonômetro portátil | Estação de monitoramento permanente (NMT) |
|---|---|---|
| Uso previsto | Operador presente, medição pontual, tripé ou mão | Instalação fixa, operação desassistida 24/7 |
| Exemplos | Instrutherm DEC-7000 e similares | Svantek SV 307A / SV 303, Nanoenvi dB, Acoem/01dB, CRY2851 |
| Proteção | Não projetado para exposição permanente | Gabinete à prova de intempéries, tipicamente IP65 |
| Conectividade | Leitura local, às vezes serial/USB | Modem 4G integrado, acesso remoto, telemetria em nuvem |
| Verificação de calibração | Operador vai ao local com calibrador | Autoverificação contínua + fonte sonora integrada para validação remota |
| Adequado ao ECOAR? | **Não** | **Sim** |

**A categoria correta para o ECOAR é a estação de monitoramento permanente
(Noise Monitoring Terminal — NMT).** O sonômetro portátil foi descartado porque
exige operador presente, o que contraria o princípio central do produto:
operação totalmente remota, sem ninguém no local.

**Por que a NMT resolve o problema de operação desassistida**

O ponto mais delicado de medição legal desassistida é garantir que o
instrumento continua calibrado sem alguém ir verificar. As estações
profissionais resolvem isso de duas formas combinadas:

- **Autoverificação contínua**: o SV 307A, por exemplo, usa array de múltiplos
  microfones para checagem dinâmica em tempo real, disparando alarme
  automaticamente se detectar divergência entre as medições
- **Fonte sonora integrada**: permite validação de desempenho automática ou
  acionada remotamente, sem deslocamento de equipe

Nota técnica relevante: o SV 307A foi a primeira estação de monitoramento de
ruído do mundo com microfone MEMS a receber aprovação Classe 1 do PTB, em
conformidade com a IEC 61672 — o que confirma que a tecnologia MEMS usada no
array do ECOAR é compatível com exigência metrológica de alto nível.

**MONTAGEM FÍSICA — CONJUNTO INTEGRADO, NÃO EQUIPAMENTO SEPARADO**

Correção em relação à versão anterior deste manual: **o instrumento de medição
faz parte do conjunto instalado no poste, não é peça separada em tripé.**

O que continua sendo verdade — e é limitação física, não escolha de projeto:

- **A cápsula do microfone precisa ficar exposta ao ar.** Nenhum instrumento
  acústico mede corretamente dentro de caixa vedada. Mas "exposta" significa
  projetada para fora do gabinete, em haste curta, com kit de proteção externa
  (anti-vento, anti-chuva, anti-pássaro/inseto) — exatamente como a lente de
  uma câmera de monitoramento fica para fora do seu invólucro. É parte do
  conjunto, não equipamento avulso
- **A eletrônica do instrumento fica protegida**, dentro do gabinete próprio da
  NMT, que já vem com proteção IP65 de fábrica
- **Não se deve abrir ou desmontar o instrumento certificado** para embutir a
  eletrônica dele na caixa do ECOAR — isso invalida a certificação. O que se
  integra é a montagem no mesmo suporte/poste e a comunicação de dados
- **A integração é de dados, não mecânica**: a NMT expõe os valores de dB por
  rede (4G/Ethernet) ou porta digital; o Raspberry Pi consome esses valores como
  mais uma fonte de dados no pacote de evidência

Resultado: uma única instalação, um único ponto de manutenção, zero operador em
campo durante a operação.

**Ressalva honesta sobre manutenção:** operação desassistida não significa
manutenção zero. Fabricantes de estações permanentes recomendam manutenção e
calibração programadas em intervalos definidos. A autoverificação remota reduz
drasticamente a necessidade de visita, mas uma verificação metrológica
presencial periódica (tipicamente anual) continua sendo boa prática — e deve
estar prevista no contrato como manutenção programada, não como operação diária.

**IMPACTO DE CUSTO (relevante para o planejamento)**

Uma NMT Classe 1 é um instrumento profissional, com preço muito acima de um
sonômetro portátil de entrada. Isso muda materialmente a economia do nó em modo
de autuação, e precisa ser considerado no dimensionamento de qualquer proposta.

**Estratégia por fase — o que compensa em cada momento:**

- **Fase de piloto / `modo=triagem`**: NÃO é necessário instrumento certificado.
  O objetivo é mapear padrão relativo (onde e quando há mais ocorrências), não
  produzir medição com validade legal. O array MEMS próprio do ECOAR resolve
  isso a custo baixíssimo. Uma NMT de classe inferior ou um sonômetro de
  referência usado apenas em campanhas de calibração pontuais pode ser
  suficiente para ancorar as medições
- **Fase de operação / `modo=autuacao`**: aí sim a NMT Classe 1 integrada passa
  a ser obrigatória — mas nesse cenário já existe contrato maduro, regulamentação
  federal definida e orçamento compatível

Essa separação por fase é o que mantém o piloto viável financeiramente sem
comprometer o desenho final do produto.

- **LGPD** — a placa capturada é dado pessoal (identifica o proprietário via Detran). O sistema precisa ter política de retenção definida (por quanto tempo guarda a foto se não virar multa) e minimização (não capturar rosto do condutor, só placa e veículo)
- **Base legal municipal já favorável** — Bauru já tem a Lei Ordinária 7816/2024 (específica para escapamento de moto) e legislação mais antiga sobre sossego público, o que facilita a fundamentação da autuação
- **Protocolo de defesa/contestação** — o cidadão autuado precisa ter caminho claro para contestar, com acesso ao pacote de evidência

---

## 8. VISÃO COMPUTACIONAL E APRENDIZADO CONTÍNUO

### 8.1 Papel da visão computacional

- **Confirmação de tipo de veículo**: antes de aceitar a leitura de placa como prova válida, um classificador de imagem confirma que o veículo no quadro é de fato uma motocicleta — evita que um carro passando ao mesmo tempo seja autuado por engano
- **Desambiguação de tráfego simultâneo**: quando dois veículos passam próximos, a posição/trajetória detectada por visão computacional é cruzada com o ângulo estimado pelo array de microfones (seção 4), para decidir qual veículo é a fonte real do som
- **Verificação cruzada de placa**: rodar dois modelos independentes de OCR sobre a mesma imagem e exigir concordância entre eles antes de aceitar a leitura como prova — reduz erro de digitação automática que poderia gerar multa para o veículo errado

### 8.2 Aprendizado contínuo — desenho seguro

Aprendizado automático direto com dado de rua tem dois riscos que precisam ser neutralizados no desenho, não corrigidos depois:

1. **Esquecimento catastrófico** — se o modelo reaprende só com dado novo, pode piorar em casos antigos que já acertava. Mitigação: todo re-treino usa uma mistura de dado novo + amostra fixa do dado histórico (nunca substituição total).
2. **Viés autoalimentado** — se o modelo erra de forma sistemática (ex: um tipo de moto, uma condição de iluminação) e ninguém corrige, ele aprende o próprio erro como padrão. Mitigação: nenhum dado vira treino sem confirmação humana.

**Ciclo de aprendizado:**

```
Evento capturado → Classificador decide (score de confiança)
   → Operador humano confirma ou rejeita (etapa já prevista no pacote de evidência, seção 6)
   → Só a confirmação humana vira dado de treino rotulado — nunca a captura bruta
   → Re-treino em lote (semanal/mensal), nunca em tempo real
   → Modelo novo só entra em produção após validar contra um conjunto de teste fixo,
     confirmando que não piorou em casos que já acertava
```

Isso é o mesmo princípio de verificado vs. inferido aplicado ao ciclo de treino: o modelo só evolui com o que foi validado por humano, nunca com a própria previsão não confirmada.

### 8.3 Retenção de dado e LGPD (ajuste necessário)

Guardar imagem/áudio por mais tempo para virar dado de treino é uma finalidade de tratamento distinta de "gerar prova de infração" — precisa de base legal e prazo de retenção próprios, definidos explicitamente na política de dados, não implícitos. Dado usado para treino deve ser anonimizado sempre que possível (ex: mascarar a placa depois que a etapa de confirmação humana já extraiu a informação necessária).

---

## 9. ESTRUTURA DE CONSTRUÇÃO — SISTEMA PRÓPRIO, VIA CLAUDE CODE

Decisão de arquitetura: o sistema é construído como produto independente seu — não como plugin ou integração com o sistema interno da prefeitura. A prefeitura recebe acesso (dashboard, API, ou exportação de dados), mas a stack, o código e a propriedade intelectual são seus, do início ao fim. Isso facilita replicar para outras cidades depois de validado em Bauru, sem depender de contrato de integração de cada município.

### 9.1 Por que Claude Code se encaixa bem aqui

Claude Code é uma ferramenta agente de linha de comando/desktop/mobile que permite delegar tarefas de programação — dá para construir os módulos abaixo iterativamente, testando e ajustando, mesmo sem experiência prévia de programação, desde que as decisões de arquitetura (como as deste manual) estejam claras primeiro. É exatamente o motivo de termos fechado o desenho técnico antes de ir para o código.

### 9.2 Estrutura de repositório sugerida

```
radar-sonoro/
├── edge/                      # Código que roda no Raspberry Pi CM4 (nó de campo)
│   ├── audio_capture/         # Captura dos 4-6 microfones (I2S)
│   ├── localization/          # GCC-PHAT — estimativa de ângulo de chegada
│   ├── classifier/            # Modelo de classificação de assinatura acústica
│   ├── camera_trigger/        # Aciona câmera ANPR quando confiança > limiar
│   └── evidence_packager/     # Monta pacote: áudio+foto+metadado+hash
│
├── vision/                    # Módulo de visão computacional
│   ├── vehicle_type/          # Confirma se é motocicleta
│   ├── plate_ocr/             # Dois modelos de OCR + verificação cruzada
│   └── trajectory/            # Desambiguação de tráfego simultâneo
│
├── backend/                   # Nuvem — ingestão, fila, validação
│   ├── ingestion_api/         # Recebe pacotes dos nós via HTTPS/MQTT
│   ├── review_queue/          # Fila de eventos aguardando validação humana
│   ├── training_pipeline/     # Re-treino em lote com dado confirmado
│   └── audit_log/             # Trilha de auditoria imutável (hash-chain)
│
├── dashboard/                 # Painel do operador (validação + métricas)
│
├── docs/
│   ├── legal/                 # LGPD, cadeia de custódia, protocolo de contestação
│   └── field-notes/           # Registro das gravações de teste em Bauru
│
└── infra/                     # Deploy, configuração de nós, CI/CD
```

### 9.3 Ordem de construção recomendada (evita retrabalho)

1. **`edge/audio_capture` + `localization`** — validar que o array de microfones localiza direção corretamente, com gravações de teste reais (o passo mais barato, sugerido no fim deste manual)
2. **`edge/classifier`** — treinar primeira versão do modelo com as amostras rotuladas de Bauru
3. **`vision/vehicle_type` + `plate_ocr`** — só depois que a parte de áudio já discrimina bem, para não gastar esforço de visão computacional em eventos que o áudio já descartaria
4. **`backend/ingestion_api` + `review_queue` + `dashboard`** — pipeline de ponta a ponta com um nó só, em modo "captura sem multa"
5. **`backend/training_pipeline`** — só depois de ter volume real de confirmações humanas acumuladas (não faz sentido antes disso)
6. **`docs/legal`** — em paralelo desde o início, não como etapa final

### 9.4 Ponto de eficiência de token, aplicado aqui

Cada módulo acima é uma sessão de trabalho separada no Claude Code, com contexto pequeno e focado (só o módulo em questão, não o repositório inteiro) — isso mantém as sessões de desenvolvimento eficientes e evita que o agente precise reler todo o histórico do projeto a cada ajuste. O `docs/` serve como memória compacta entre sessões: decisões já tomadas ficam registradas ali, não é preciso reconstruir o raciocínio do zero a cada vez que você volta ao projeto.

---

## 9.5 PLATAFORMA DE GESTÃO — ONDE O USUÁRIO OPERA

A parte que faz o sistema ser usável no dia a dia, não só tecnicamente funcional.

**Dois perfis de acesso**

| Perfil | O que vê e faz |
|---|---|
| Operador municipal (Secretaria de Trânsito/Seplan) | Revisa e confirma/rejeita eventos, consulta histórico, exporta relatório e pacote de autuação |
| Admin (dono do produto) | Tudo do operador + gestão de nós, versão de modelo, auditoria completa, e — na expansão futura — visão isolada por município |

**Telas principais**

1. **Mapa de nós** — status de cada sensor instalado (online/offline, bateria, última captura)
2. **Fila de revisão** — tela de maior uso diário: áudio, foto da placa, ângulo estimado e score de confiança lado a lado, com confirmar/rejeitar (backend/review_queue)
3. **Histórico** — busca e filtro de eventos já decididos, essencial para recuperar evidência em caso de recurso administrativo
4. **Métricas e relatórios** — eventos por dia/local, taxa de falso positivo ao longo do tempo, comparação de custo com blitz manual — vira o argumento de renovação de contrato
5. **Gestão de modelo** — histórico de versões do classificador, resultado de cada re-treino (backend/training_pipeline), com opção de reverter versão
6. **Auditoria** — visualização da trilha de hash-chain (backend/audit_log), para resistir a contestação judicial
7. **Configurações** — limiar de confiança, calibração de SPL por sensor, política de retenção (LGPD), permissão de usuário
8. **Exportação** — gera o pacote formal (PDF + evidência anexada) para o operador municipal levar ao sistema de autuação da própria prefeitura — exportação simples, não integração profunda, mantendo o sistema independente

---

## 9.6 IDENTIDADE DO PRODUTO

**Nome: ECOAR**

Vem de "ecoar" — o som que volta, que se confirma. Encaixa com o núcleo do produto: o sistema não apenas ouve, ele confirma o que ouviu antes de agir. É curto, fácil de falar numa reunião com prefeitura, e não soa agressivo ou punitivo (evita nomes tipo "Radar", "Multa Já", que reforçam a imagem de fiscalização hostil).

Tagline sugerida: **"Ouve. Confirma. Prova."** — resume o pipeline inteiro (captura sonora → validação humana → evidência auditável) em três palavras, e comunica exatamente o diferencial jurídico do produto frente ao concorrente de São José dos Campos.

**Tipografia**

| Uso | Fonte | Motivo |
|---|---|---|
| Títulos e identidade de marca | Manrope (ou Space Grotesk) | Geométrica, moderna, transmite tecnologia sem parecer fria/corporativa demais — adequada para pitch e material institucional |
| Corpo de texto e interface do dashboard | Inter | Altíssima legibilidade em telas pequenas e densidade de dados, padrão de mercado para produtos de dados/dashboard |
| Dados técnicos e leituras (dB, timestamps, hash) | JetBrains Mono | Fonte monoespaçada — comunica precisão técnica e facilita a leitura de valores numéricos/códigos, reforça a seriedade da evidência |

**Paleta**

Sugestão de manter consistência com a identidade já existente de Studio Cerne (estética editorial escura, laranja #FF6B35 como cor de assinatura), com adição de duas cores funcionais específicas do ECOAR:

- **Base**: escuro editorial (mesma linha do Studio Cerne) — transmite seriedade institucional
- **Âmbar de alerta** (`#F5A623` ou similar): estados de "evento pendente de revisão" — evita vermelho puro, que soa como culpa já definida antes da validação humana
- **Verde de confirmação** (`#2ECC71` ou similar): eventos confirmados/validados
- **Laranja Studio Cerne** (`#FF6B35`): mantido como cor de assinatura da marca-mãe, usado com moderação (logo, links de destaque), não como cor operacional do dashboard

---

## 9.7 PROTEÇÃO PATRIMONIAL E MEDIDAS ANTIFURTO

Equipamento instalado em via pública é alvo. Essa é uma das primeiras objeções
que qualquer prefeitura levanta — e a resposta precisa ser estruturada em
camadas, não uma promessa genérica de "é resistente".

### 9.7.1 A decisão de arquitetura que mais reduz risco (por fase)

O item de maior valor do nó é o instrumento de medição certificado (NMT). A
exposição patrimonial é diferente em cada fase do projeto, e isso precisa ser
comunicado com precisão — não como promessa genérica.

**Em `modo=triagem` (fase de piloto):**

Não há instrumento certificado permanentemente instalado. O nó carrega apenas
componentes de baixo valor unitário e baixa liquidez no mercado ilegal
(Raspberry Pi, microfones MEMS, câmera, módulo 4G) — o conjunto todo tem valor
de revenda desprezível. **Esse é o argumento correto para a fase de piloto, e é
verdadeiro.**

**Em `modo=autuacao` (operação contratada):**

A NMT Classe 1 fica permanentemente integrada ao conjunto — é requisito de
operação desassistida, não escolha. Aqui o valor exposto é alto e a proteção
precisa vir das outras camadas (física, eletrônica e contratual), além de
fatores que só existem nessa fase:

- Instalação em pontos já cobertos por câmeras municipais
- Contrato de operação com seguro do equipamento previsto e precificado
- Orçamento compatível com blindagem física de maior nível

**Como comunicar isso corretamente em reunião:** não afirme que "o equipamento
caro nunca fica no poste" como se valesse para sempre — isso é verdade no
piloto, não na operação final. A formulação honesta é: *"no piloto, o que fica
instalado tem valor de revenda desprezível; na operação contratada, o
equipamento de medição é permanente e vem com seguro e proteção dimensionados
para isso."*

### 9.7.2 Camada 1 — Dissuasão (impedir que tentem)

| Medida | Detalhe |
|---|---|
| Altura de instalação | Mínimo 4,5–5 m, fora de alcance sem escada ou escalada — a maioria dos furtos de oportunidade morre aqui |
| Identificação visível | Placa "Equipamento público monitorado — Prefeitura Municipal de [cidade]". Furto de bem público tem tratamento penal mais severo, e a sinalização reduz a tentativa oportunista |
| Patrimoniamento | Numeração de patrimônio municipal gravada nos componentes, dificultando revenda |
| Escolha do ponto | Priorizar postes em área iluminada e, quando possível, dentro do campo de visão de câmeras municipais já existentes — os sistemas se protegem mutuamente |

### 9.7.3 Camada 2 — Barreira física (dificultar a remoção)

| Medida | Detalhe |
|---|---|
| Parafusos antifurto | Torx de segurança com pino central, cabeça unidirecional ou parafuso de cisalhamento — não abrem com ferramenta comum |
| Fixação por cinta metálica | Cinta de aço inox com fecho selado, em vez de suporte parafusado acessível |
| Conduíte blindado | Cabeamento externo (alimentação, cabo do sonômetro quando presente) dentro de conduíte metálico flexível, resistente a corte rápido |
| Gabinete reforçado | Caixa metálica com fechadura de chave restrita. **Atenção técnica:** gabinete metálico atenua sinal 4G — a antena precisa ser externa ao gabinete, com passagem vedada |
| Lacre evidenciador | Lacre numerado que evidencia abertura, útil também para cadeia de custódia |

### 9.7.4 Camada 3 — Detecção eletrônica (saber na hora)

Esta camada vira um módulo de software próprio (ver Prompt 12):

- **Acelerômetro/giroscópio (MPU-6050)**: detecta movimento, impacto ou
  inclinação anômala do gabinete → alerta imediato
- **Sensor de abertura**: chave magnética (reed switch) na tampa → alerta ao
  abrir
- **Detecção de corte de energia**: queda da alimentação principal com bateria
  assumindo → alerta, e a bateria de backup mantém o rádio 4G vivo o suficiente
  para transmitir
- **Heartbeat de conectividade**: o nó envia sinal de vida periódico; ausência
  por N minutos acende alerta no dashboard (tela de mapa de nós)
- **Captura automática sob violação**: ao detectar violação, a câmera dispara
  captura e faz upload imediato antes de qualquer desligamento — a tentativa de
  furto vira a própria evidência

### 9.7.5 Camada 4 — Resposta contratual (quem assume o prejuízo)

Esta é a camada que mais pesa na decisão da prefeitura, e a que menos depende
de engenharia:

- **Seguro do equipamento** contratado pelo fornecedor, não pelo município,
  embutido no valor do contrato
- **Risco de furto assumido pelo fornecedor** durante a fase de piloto/PoC —
  argumento comercial forte: *"se sumir, o problema é nosso, não de vocês"*
- **SLA de reposição** definido em contrato (ex: nó reposto em até X dias
  úteis), para o serviço não ficar interrompido
- **Registro de ocorrência padronizado**: procedimento definido de boletim de
  ocorrência e comunicação ao município, evitando ruído administrativo

### 9.7.6 Resposta pronta para a objeção em reunião

> "É um equipamento em via pública, sim — e o desenho já parte disso. No piloto,
> o que fica instalado são componentes de baixo valor de revenda; o instrumento
> de medição certificado só entra na fase de operação contratada, e aí já vem
> com seguro previsto em contrato. Em qualquer fase, o nó tem detecção de
> violação: acelerômetro e sensor de abertura disparam alerta, e a câmera
> fotografa e envia a imagem antes de o equipamento ser removido. E durante o
> piloto, o risco de furto é nosso, não da prefeitura."

---

## 10. PLANO DE MVP (3 nós, prova de conceito)

| Etapa | Ação |
|---|---|
| 1 | Montar 3 kits (Raspberry Pi CM4 + array de 4 microfones + câmera ANPR) e testar em bancada |
| 2 | Gravar amostras de áudio reais em pontos críticos de Bauru (Ponte São João e Centro, já documentados como áreas de reclamação recorrente) para treinar o classificador inicial |
| 3 | Instalar os 3 nós em postes nos pontos críticos, com energia da rede pública |
| 4 | Rodar por 2-4 semanas em modo "captura sem multa" — validar precisão de localização e taxa de falso positivo antes de qualquer aplicação de penalidade |
| 5 | Apresentar case com dados reais (quantos eventos, taxa de acerto, comparação de custo com blitz manual) para a Secretaria de Trânsito/Seplan |

---

## 11. LISTA DE MATERIAIS ESTIMADA (por nó)

| Item | Modelo | Preço estimado (R$) |
|---|---|---|
| Computador de borda | Raspberry Pi CM5 (4GB) + placa base — CM4 é alternativa equivalente | 450-550 |
| Microfones MEMS (4x) | SPH0645LM4H (I2S) — substituto direto confirmado do ICS-43434, descontinuado em 2026 | 120 |
| Câmera ANPR | Módulo com IR para leitura noturna de placa | 350 |
| Módulo 4G/LTE | Quectel EC25 — CONFIRMAR ESTOQUE antes de comprar (série com sinal de EOL em alguns distribuidores); EC200A-EU ou EG25-G são alternativas compatíveis | 180 |
| Case IP65 + suporte de poste | Fabricação sob medida | 150 |
| Fonte/bateria backup | Fonte 12V + bateria de gel 7Ah | 130 |
| **Subtotal por nó** | | **~R$ 1.380** |

### Itens de proteção patrimonial (ver 9.7)

| Item | Especificação | Custo estimado (R$) |
|---|---|---|
| Acelerômetro/giroscópio | MPU-6050 (detecção de violação) | 15 |
| Sensor de abertura | Chave magnética reed switch | 10 |
| Parafusos antifurto | Torx de segurança com pino / cabeça unidirecional | 40 |
| Cinta de fixação | Aço inox com fecho selado | 60 |
| Conduíte blindado | Metálico flexível, para cabeamento externo | 50 |
| Lacre numerado | Evidenciador de abertura | 10 |
| **Subtotal proteção** | | **~R$ 185** |
| **TOTAL POR NÓ (modo=triagem)** | | **~R$ 1.565** |

**⚠️ Nota de disponibilidade (agosto/2026):** o ICS-43434 foi oficialmente descontinuado pelo fabricante (TDK InvenSense) — a lista acima já reflete o substituto direto confirmado (SPH0645LM4H, mesmo pinout). O módulo Quectel EC25 tem sinal misto de disponibilidade entre distribuidores — confirme estoque atual antes de fechar compra, e tenha EC200A-EU/EG25-G como plano B. Recomenda-se revisar esta lista a cada nova rodada de compra, não assumir que ela continua atual indefinidamente.

### Instrumento de medição certificado (apenas em `modo=autuacao`)

| Item | Especificação | Custo |
|---|---|---|
| Estação de monitoramento permanente (NMT) Classe 1 | Ex: Svantek SV 307A/SV 303, Nanoenvi dB, Acoem/01dB, CRY2851 — com saída de dados digital, autoverificação remota e certificação metrológica | A cotar |

**Atenção ao dimensionar proposta:** uma NMT Classe 1 é instrumento
profissional e representa um salto expressivo no custo do nó — muito acima de
tudo somado acima. Por isso a separação por fase importa: no piloto em modo de
triagem esse item não é necessário, e a economia do MVP se mantém viável. Cote
com pelo menos três fornecedores antes de propor valor de operação contratada.

Observação de custo: a proteção patrimonial adiciona ~13% ao custo do nó — bem
abaixo do custo de perder um nó inteiro, e serve como argumento comercial
direto na conversa com a prefeitura.

Mais caro que o Sentinel (bueiro) porque exige mais poder de processamento — mas ainda é uma fração do custo de um array profissional de 21 microfones como o de SJC.

---

## 12. ROADMAP MODULAR — ALÉM DO RUÍDO DE ESCAPAMENTO

O hardware do ECOAR (array de microfones + câmera + computador de borda +
conectividade) não é dedicado a um único problema. É uma plataforma de
sensoriamento urbano que hoje está *configurada* para escapamento adulterado,
porque foi essa a demanda que originou o projeto. Outros módulos são
reconfiguração de software sobre o mesmo equipamento, não produto novo.

Esta seção existe para uso comercial: ter clareza do que é seguro oferecer
como complemento imediato numa reunião, e o que é apenas direção futura — para
não prometer mais do que está pronto para sustentar.

### 12.1 Nível 1 — Pronto para mencionar como complemento na reunião

Reaproveitam hardware já especificado no nó (câmera ou array de microfones),
sem sensor adicional, sem nova base legal complexa, e falam diretamente com
quem normalmente está na sala (Secretaria de Mobilidade/Trânsito):

| Módulo | Como funciona | Reaproveita |
|---|---|---|
| **Contagem e classificação de tráfego** | A câmera ANPR já instalada classifica veículos por tipo (moto/carro/ônibus) e gera volume por horário e local | Câmera (mesma usada para escapamento) |
| **Detecção de obra fora de horário permitido** | O classificador de assinatura acústica é retreinado para reconhecer britadeira/marreta, aplicando a mesma Lei do Silêncio | Array de microfones + classificador |

**Como apresentar:** mencionar como parte natural do mesmo sistema, não como
proposta separada — "o mesmo sensor que capta escapamento também gera esse
dado, sem custo adicional".

### 12.2 Nível 2 — Direção futura, mencionar com cautela

Tecnicamente viável com o mesmo hardware, mas envolve outra secretaria,
integração com base de dados externa, ou tema sensível o suficiente para não
ser o foco de uma primeira reunião comercial:

| Módulo | Como funciona | Observação |
|---|---|---|
| **Detecção de disparo de arma de fogo** | Array de microfones + triangulação + classificador de assinatura acústica localizam e classificam disparo em segundos | Precedente real: Niterói opera o ShotSpotter (SoundThinking) com exatamente essa arquitetura, integrado ao Centro Integrado de Segurança Pública. Relevante para Segurança Pública/Guarda Municipal, não para Mobilidade — assunto de outra conversa, outro comprador |
| **Cruzamento de placa com veículos furtados/roubados** | A câmera ANPR já lê placa; cruzaria com base de ocorrência policial | Exige acesso a base de dados de segurança pública e autorização formal — complexidade jurídica que não deve entrar numa reunião inicial |
| **Detecção de acidente/colisão** | Reconhece padrão acústico de frenagem brusca + impacto | Módulo ainda não especificado tecnicamente; mencionar apenas como direção, não como capacidade |

### 12.3 Nível 3 — Produto adjacente, não módulo do ECOAR

Usam a mesma infraestrutura de poste (energia, conectividade, gabinete), mas
exigem sensor físico adicional — é outro produto vendido em conjunto, não uma
função nova do mesmo equipamento:

| Módulo | Sensor adicional necessário | Observação |
|---|---|---|
| Monitoramento de iluminação pública | Sensor de luminosidade (baixo custo) | — |
| Qualidade do ar | Sensor de PM2.5/gases (~R$150-300) | — |
| Monitoramento de enchente/nível de água | Sensor ultrassônico | Já especificado no projeto Sentinel — mesma rede de postes pode compartilhar infraestrutura, mas é produto separado |

### 12.4 Regra de uso comercial

Nível 1 pode ser oferecido como parte da proposta atual. Nível 2 só deve ser
mencionado se a conversa abrir espaço natural para isso (ex: pergunta direta
sobre segurança pública) — nunca como pitch principal fora de contexto. Nível
3 nunca deve ser tratado como parte do ECOAR — é cross-sell de outro produto,
com sua própria proposta e ciclo de venda.

### 12.5 Prompts de construção

Contagem de tráfego, cruzamento com veículos furtados/roubados, detecção de
acidente/colisão e detecção de disparo de arma de fogo já têm prompt preparado
em `docs/projeto/prompts-claude-code.md` (Prompts 13-16). Os dois primeiros são
prompts de construção; os dois últimos são deliberadamente estudos de
viabilidade, não construção — nenhum dos dois tem especificação técnica
validada ainda, e o de disparo de arma muda quem é o comprador do produto (ver
seção 12.2).

---

## 13. PRÓXIMO PASSO TÉCNICO IMEDIATO

Antes de comprar qualquer hardware: gravar áudio de teste em campo (mesmo com celular) nos pontos citados nas notícias de Bauru, para validar se dá pra distinguir a assinatura de escapamento adulterado de outros ruídos urbanos com um modelo simples. Isso é barato, rápido, e responde a pergunta mais arriscada do projeto antes de qualquer investimento em hardware.

---

*Este manual é uma proposta técnica de arquitetura, não uma implementação testada em campo. Validação de precisão real (taxa de falso positivo, alcance de detecção) depende de testes com hardware físico nas condições específicas dos pontos críticos de Bauru.*
