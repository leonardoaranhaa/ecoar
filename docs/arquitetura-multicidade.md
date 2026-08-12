# ARQUITETURA DO PRODUTO MULTI-CIDADE

Documento de planejamento. **Nenhum código deste desenho foi escrito ainda** — é
para revisar antes de construir. Quando aprovado, cada seção vira uma etapa, no
mesmo ritmo do MVP (uma por vez, com teste, sem hardware).

O que está no repositório hoje é um **MVP de uma operação só**. Este documento
descreve a virada dele em **produto multi-cidade (SaaS)**, que o manual do
projeto já antecipava ("produto independente, replicável para outras cidades",
"visão isolada por município").

---

## 0. O que NÃO muda

Antes de tudo: as decisões inegociáveis do `docs/DECISIONS.md` continuam valendo
inteiras. Multi-cidade é uma camada por cima, não uma reescrita.

- validação humana em todo evento (D2);
- decisão de acionamento determinística e versionada (D7);
- fail-closed (D8);
- array MEMS ≠ medição legal (D3), `modo=autuacao` travado sem base normativa;
- nenhuma leitura de placa no nó (D10), log/trilha sem dado pessoal (D6);
- cadeia de custódia e trilha hash-chain (D9);
- hardware atrás de interface, suíte roda sem componente físico (D11);
- acesso a dados isolado em `backend/db.py` (D12) — é o que torna esta virada
  contida.

Se algum item deste plano colidir com uma dessas, o item está errado, não a
decisão.

---

## 1. Onde estamos × onde queremos chegar

| Dimensão | MVP hoje | Produto multi-cidade |
|---|---|---|
| Cidades | uma, implícita | muitas, isoladas entre si |
| Banco | SQLite, um arquivo | Postgres, dado carimbado por município |
| Login de pessoa | token estático digitado | usuário + senha, papel por município |
| Auth do nó | token estático no YAML | credencial por nó (token → mTLS na operação) |
| Cadastro de equipamento | implícito (aparece quando telefona) | tela de registro + provisionamento |
| Config do nó | YAML editado no cartão SD | definida no painel, buscada pelo nó |
| Comando remoto ao nó | não existe | canal de comando (pull no heartbeat) |
| Mapa | não existe | mapa da cidade com os equipamentos |
| Hospedagem | nada no ar | nuvem nacional, backend central |

O ponto tranquilizador: as **telas de operação já existem** (etapa 11). O que
falta é a **camada de produto** embaixo delas.

---

## 2. Modelo de dados multi-tenant

A escolha de fundo é **um backend só, dado carimbado por município** (não uma
instância por cidade). É o que o manual pede — "replicar sem contrato de
integração por cidade" — e o que menos custa operar. Isolamento por cidade vira
regra de consulta, não infraestrutura separada.

### Entidades novas

```
municipio
  id, nome, uf, cnpj, criado_em, ativo
  # o tenant. Bauru, Piracicaba, Marília… cada um é um município.

usuario
  id, municipio_id (NULL = super-admin Studio Cerne), nome, email,
  senha_hash, papel, ativo, criado_em, ultimo_acesso
  # pessoa que faz login. Pertence a um município (ou a nenhum, se for do
  # fornecedor).

equipamento            # substitui/estende a tabela `nos` atual
  id (no_id), municipio_id, descricao, ponto (endereço),
  latitude, longitude, estado, modo,
  geometria_json (raio, n_microfones, offset), calibracao_json, limiares_json,
  registrado_por, registrado_em, primeiro_contato, ultimo_contato,
  ultimo_heartbeat, bateria_pct

credencial_no
  id, no_id, tipo (provisionamento | operacao), segredo_hash,
  emitida_em, expira_em, revogada_em
  # o token/cert do nó vive aqui, com hash — nunca em claro, nunca no YAML.

comando_no
  id, no_id, tipo, parametros_json, criado_por, criado_em,
  entregue_em, aplicado_em, resultado_json
  # fila de comandos backend → nó (ver seção 6).
```

### Carimbo por município

`eventos`, `violacoes`, `revisoes`, `heartbeats` ganham `municipio_id` (derivado
do nó que enviou). **Toda consulta** passa a receber o `municipio_id` do usuário
logado e filtra por ele — exceto o super-admin, que pode ver todos ou um
específico.

Isso é uma mudança concentrada em `backend/db.py` (D12): as funções de consulta
ganham um parâmetro de escopo. Nenhum módulo de negócio precisa saber de
município — ele pergunta ao `db.py` "os eventos deste escopo", e o `db.py`
resolve.

### Migração do banco

`backend/db.py` já tem migrações versionadas. Multi-tenancy entra como
migração 3+: cria as tabelas novas, adiciona `municipio_id`, e faz o *backfill*
(o dado existente vira o município "Bauru"). Nenhuma alteração manual de schema.

### SQLite → Postgres

O acesso a dados está isolado (D12), então a troca é contida: muda a conexão e
alguns detalhes de SQL (tipos, `datetime('now')` → `now()`). O que precisa de
atenção é a **trilha de auditoria hash-chain**: hoje ela serializa a escrita com
um lock em processo (a conexão SQLite é compartilhada entre threads). Em
Postgres com múltiplos workers, a serialização do `seq` precisa ser do banco —
`SELECT … FOR UPDATE` na última entrada, ou uma sequência transacional. É o
único ponto onde a hash-chain e o multi-worker se cruzam, e precisa ser feito
com cuidado para a cadeia não quebrar sob concorrência.

---

## 3. Papéis e acesso

Quatro papéis, dois "admins" que hoje se confundem num só:

| Papel | Quem é | Escopo | O que faz |
|---|---|---|---|
| **super-admin** | Studio Cerne (fornecedor) | todas as cidades | cadastra municípios, registra equipamentos, gere versões de modelo, auditoria completa, alterna modo |
| **admin municipal** | gestor da prefeitura | sua cidade | tudo do operador + gestão de usuários da cidade, configurações, exportação |
| **operador** | fiscal / servidor | sua cidade | revisa e decide eventos, consulta histórico e priorização |
| **instalador** | técnico de campo (Studio Cerne ou terceirizado) | equipamento designado | registra e provisiona o nó, calibra, valida em campo |

Hoje "admin" é só um operador cujo token começa com `admin`, e é global. O
RBAC precisa virar explícito (papel gravado no `usuario`), e o backend recusa
por papel **e** por município — as duas checagens, sempre. A restrição no menu
do painel continua sendo só conveniência; a garantia mora no backend.

---

## 4. Autenticação — duas coisas diferentes

Hoje tudo é token estático. Precisa separar **pessoa** de **dispositivo**,
porque são ameaças diferentes.

### Pessoas (login no painel)

- usuário + senha, senha guardada só como hash (argon2/bcrypt);
- sessão por cookie assinado ou JWT curto + refresh;
- o token estático de operador **sai** — era MVP.
- rate limiting e bloqueio por tentativa; trilha de login (sem senha, óbvio).

### Dispositivos (o nó autenticando)

- **fase piloto:** token por nó, guardado como hash em `credencial_no`, entregue
  no provisionamento — nunca mais no YAML do cartão;
- **operação contratada:** migrar para **mTLS** (certificado por nó). Já estava
  registrado como dívida no `backend/README.md`. É o que impede um nó clonado
  de se passar por outro.
- o backend continua conferindo que o token do nó bate com o nó que o manifesto
  declara (já existe hoje) — agora também com o município do nó.

---

## 5. Ciclo de vida do equipamento e provisionamento

Este é o maior buraco de hoje: o nó é registrado **implicitamente** (aparece
quando telefona) e configurado **editando YAML no cartão SD**. Não escala para
dezenas de postes em várias cidades.

### Estados do equipamento

```
cadastrado → provisionado → em_campo → ativo → (manutencao | inativo | roubado)
```

- **cadastrado:** o admin/instalador criou o nó no painel — cidade, ponto,
  geolocalização, geometria do array, limiares. Ainda não existe hardware
  associado.
- **provisionado:** foi gerada uma credencial de provisionamento (token de uso
  único, curto). O SD é gravado com essa credencial e o endereço do backend —
  nada de config sensível no cartão.
- **em_campo:** no primeiro boot, o nó usa a credencial de provisionamento para
  **buscar a config do backend** (a que o admin definiu no cadastro) e receber a
  credencial de operação. A partir daí o cartão não carrega segredo permanente.
- **ativo:** enviando eventos e heartbeats.
- **manutencao / inativo / roubado:** estados operacionais; `roubado` cruza com
  o antifurto (etapa 12).

### Tela de registro (o que você pediu)

Uma tela **"registrar equipamento"** (admin/instalador) que:
1. cria o nó no município selecionado;
2. captura ponto, geolocalização (clicando no mapa — ver seção 7), e a
   geometria do array;
3. gera a credencial de provisionamento (QR code ou arquivo para o cartão);
4. acompanha o nó mudar de estado conforme ele entra em campo.

### "Conecto a placa e ela recebe comandos?"

Hoje **não** — o nó só empurra eventos e heartbeats. Com o canal de comando
(seção 6), sim: você registra no painel, grava o cartão, o nó sobe, busca a
config, e a partir daí você **muda config e manda comando pelo painel**, sem
SSH. O que continua sendo de campo, com hardware na mão, é o físico: apontar a
câmera, conferir o ângulo (`--varrer`, checkpoint 2), calibrar. Essas ferramentas
já existem como CLI; falta embrulhá-las no fluxo de instalação.

---

## 6. Canal de comando (backend → nó)

O nó fica atrás de 4G/NAT, então **push do backend é frágil**. O padrão certo é
**pull**: o nó, a cada heartbeat, pergunta "há comando pendente?". Simples,
atravessa NAT, e reaproveita o heartbeat que já existe.

Tipos de comando previstos:

| Comando | Efeito | Guarda |
|---|---|---|
| `atualizar_config` | novo limiar, calibração, geometria | **versionado**: a config nova ganha versão, e o evento grava sob qual versão rodou (não quebra a reprodutibilidade da decisão) |
| `entrar_manutencao` / `sair` | suspende/religa o antifurto | expira sozinho (já é assim no nó) |
| `reiniciar` | reboot do serviço | idempotente |
| `atualizar_modelo` | baixa novo `.pt` do classificador | só promove se validar (D13) |
| `trocar_modo` | triagem ↔ autuação | **recusado** se não houver instrumento certificado + base normativa (D3); o comando existe, a trava também |

Regra de ouro: **nenhum comando fura as decisões inegociáveis**. Trocar para
autuação por comando remoto continua exigindo o que o `edge/config.py` já exige
hoje. O canal de comando é conveniência de operação, não uma porta dos fundos
para as travas jurídicas.

---

## 7. Mapa da cidade com os equipamentos

Hoje não há mapa: a latitude/longitude está guardada em cada nó mas só aparece
numa tabela. O que falta:

- **mapa geográfico** com um pino por equipamento, cor pelo estado
  (ativo / sem sinal / manutenção / violação), clique abre o detalhe do nó;
- **usado também no cadastro** (seção 5): o instalador marca o ponto clicando no
  mapa, em vez de digitar coordenada;
- a **priorização** pode ganhar uma camada de mapa de calor **geográfico** da
  cidade, complementando o mapa de calor hora×dia que já existe.

**Restrições a decidir** (por isso está no plano, não no código):
- o painel é "sem build, self-contained". Um mapa usa biblioteca (ex.: Leaflet) e
  **tiles** (as imagens do mapa). Tiles vêm de um servidor externo — o que
  colide com a preferência de "território nacional / sem dependência externa".
  Opções: tiles do OpenStreetMap, um provedor nacional, ou um servidor de tiles
  próprio. **É uma decisão de produto que vale a pena tomar antes de codar.**
- offline: se o painel precisar funcionar sem internet externa (só com a rede do
  município), o servidor de tiles próprio passa a ser necessário.

---

## 8. Hospedagem e modus operandi

```
        ┌─────────────────────── nuvem nacional (LGPD) ───────────────────────┐
        │                                                                     │
        │   backend FastAPI  ──  Postgres  ──  object storage (pacotes)       │
        │        │  TLS                                                        │
        │        └── painel web (mesmo serviço)                               │
        └──────────────────────────────┬──────────────────────────────────────┘
                        HTTPS/4G        │        HTTPS (navegador)
              ┌─────────────────────────┼──────────────────────┐
              ▼                         ▼                        ▼
      nó Bauru-01 (Pi)         nó Piracicaba-03 (Pi)      prefeitura (operador)
      edge/, autônomo          edge/, autônomo            painel, só a sua cidade
```

- **Backend central** operado pelo Studio Cerne (o "S" de SaaS): um serviço,
  todos os municípios, dado isolado por tenant. Hospedagem **nacional** (LGPD +
  "território nacional desde o dia 1").
- **Postgres** no lugar do SQLite; **object storage nacional** para os pacotes
  `.ecoar` (hoje ficam em disco local — o `armazenamento.py` já foi desenhado
  para essa troca).
- **Cada nó** roda o `edge/` e é autônomo: backend fora do ar não para a
  captura, o `uplink` enfileira e reenvia. Isso já funciona.
- **Cada prefeitura** acessa o painel por URL, vê só a sua cidade.
- **TLS obrigatório** nó→backend: o `edge/config.py` já recusa HTTP sem TLS para
  endereço não-local.

---

## 9. Caminho de migração (sem reescrever)

O MVP não é jogado fora — ele é a fundação. Ordem sugerida, cada uma testável
sem hardware:

1. **Fundação multi-tenant + login** — entidades `municipio`/`usuario`, carimbo
   por município nas consultas (contido no `db.py`), papéis, login de verdade.
   *Base de tudo: mapa e cadastro dependem de "qual cidade" e "quem é você".*
2. **Cadastro e provisionamento de equipamento** — tela de registro, credencial
   por nó, e o canal de comando (pull no heartbeat). O nó passa a buscar config
   do backend em vez de YAML no cartão.
3. **Mapa da cidade** — depois da decisão de tiles (seção 7).
4. **Postgres + deploy nacional** — pode vir em paralelo a partir da fase 1,
   porque o `db.py` isola a troca.

As etapas 8 (visão) e 9 (re-treino) do roteiro original continuam esperando
**dado de campo de Bauru** — este plano não as antecipa nem depende delas.

---

## 10. Decisões (fechadas na revisão do PR #2)

As cinco foram respondidas. O fio condutor: **priorizar o que serve à fase de
piloto/demonstração, até a formulação de contrato ou pivô.** Não sobre-investir
em infra de produção antes de existir contrato.

| # | Decisão | Resposta | O que fica |
|---|---|---|---|
| 1 | Tiles do mapa | avaliar para piloto/teste até contrato ou pivô | **Demo:** mapa esquemático self-contained (sem tile externo, offline, custo zero). **Piloto:** tiles OSM públicos (grátis, bom o suficiente). **Só se um contrato exigir** soberania/offline: tile server próprio/nacional. Nada de servidor de tiles agora. |
| 2 | Login | simplificado por hora, para apresentação | Seletor de cidade + papel, sem senha, rotulado "demonstração". Login com senha de verdade fica para quando houver contrato. |
| 3 | Isolamento | **multi-tenant confirmado** | Um backend só, dado carimbado por município (seção 2). |
| 4 | Config do nó | seguir a recomendação | Buscada do backend no boot; o cartão SD não carrega segredo permanente (seção 5). |
| 5 | Onde hospedar | sem provedor em mente; pediu sugestão demonstrativa | Ver seção 11: a demo **não precisa de hospedagem** (é self-contained e compartilhável). Para um piloto ao vivo depois da reunião, um VPS pequeno em provedor nacional basta — sem infra de produção pré-contrato. |

Com isso, a **seção 11** vira o próximo passo concreto (a demo), e a fase 1 do
caminho de migração (fundação multi-tenant, seção 9) fica pronta para virar
código quando o contrato/piloto justificar.

---

## 11. Demonstração para a reunião de produto

O que a reunião precisa não é infra, é **algo clicável que conte a história do
produto**: várias cidades, o mapa com os equipamentos, e o painel que a
prefeitura usaria. Barato, sem risco de demo ao vivo travar, e honesto sobre o
que é (demonstração, não sistema em produção).

### O que mostrar (a narrativa de 5 minutos)

1. **Os pontos escolhidos** — a coluna "Local" nomeia por que cada ponto entrou:
   operação da Semuttran na Av. Presidente Kennedy, requerimentos da Câmara,
   polo de lazer da Rua do Porto. Abre a conversa mostrando que houve
   levantamento, não chute. (Ver `docs/field-notes/piracicaba.md`.)
2. **Priorização** — o mapa de calor hora×dia que já existe, com dado realista.
   É o argumento central: "onde e quando mandar a blitz".
3. **Fila de revisão** — abrir um evento, ouvir o áudio, ver as regras que o nó
   avaliou, confirmar. Mostra a validação humana e a evidência auditável.
4. **Uma frase de honestidade** em cada tela sensível: SPL sem valor legal, não
   gera multa, dado de campo ainda não coletado. É o que dá credibilidade
   técnica na primeira pergunta de um engenheiro da prefeitura.

### Como entregar — duas opções, e a recomendação

**Opção A — página de demonstração self-contained (recomendada para a reunião).**
Um único arquivo HTML, dado realista embutido, mapa esquemático da cidade
desenhado em SVG (sem tile externo). Abre em qualquer navegador, celular
inclusive, **sem instalar nada e sem internet**. Dá para mandar o link antes da
reunião e abrir no telão ou no celular. Risco zero de travar. Limite honesto: é
um mockup navegável com dado de exemplo, e é rotulado como tal.

**Opção B — o sistema real rodando, com dado semeado.** ✅ **construída.**
É o backend + painel que já construímos (etapa 11), semeado com o cenário de
Piracicaba (cinco pontos), rodando no notebook do
apresentador ou num VPS. Mais convincente para plateia técnica (é o sistema de
verdade, não desenho), mas exige subir algo e tem risco de demo ao vivo.

O seed vive em `scripts/semear_demo.py` e a config em `config/backend.demo.yaml`:

```bash
python -m scripts.semear_demo --config config/backend.demo.yaml --recriar
python -m backend.cli --config config/backend.demo.yaml
# http://127.0.0.1:8000/  — token operador ou admin de config/backend.demo.yaml
```

Cada evento semeado é um pacote `.ecoar` real, enviado pela ingestão real (hash
revalidado na entrada) e decidido pela fila de revisão real (a trilha de
auditoria encadeia cada decisão — a demo verifica ~447 entradas íntegras). É a
prova do multi-tenant na base: **um backend, muitas instalações**. O isolamento
por município (login por cidade) é a fase seguinte descrita nas seções acima.

Para levar essa demo a uma reunião num servidor, o kit de deploy está em
`deploy/`: Docker Compose que constrói a imagem, semeia no primeiro boot e sobe
o painel em `IP:8000`, com tokens fortes gerados por `deploy/gerar-env.sh` (o
`config/backend.vps.yaml` recusa subir sem eles — fail-closed). O passo a passo
do zero, incluindo escolha de VPS nacional e como pôr domínio com HTTPS depois,
está em `deploy/README.md`.

**Recomendação:** levar a **Opção A** como principal — é o "paliativo e
demonstrativo" que a reunião pede, compartilhável e à prova de falha — e ter a
**Opção B** de reserva para um aprofundamento técnico, se a conversa avançar.

### O que a demo NÃO faz (para não prometer o que não há)

- não lê placa, não gera multa, não mede dB com valor legal;
- o dado é de exemplo, gerado para a demonstração — não é captura de campo;
- o mapa da demo é esquemático; o mapa geográfico real entra no piloto.

Isso não enfraquece a demo — é o que a torna defensável. O produto se vende
justamente por **não** prometer o que não pode entregar.

### Custo e prazo

Opção A: sem custo de infra, e reaproveita todo o front-end já feito. É a
próxima etapa de código natural, se você aprovar — e cabe numa sessão.

## 12. Backlog de UX (pós-reunião)

Itens levantados na avaliação da demo, para versões posteriores:

- **Tour guiado no produto real.** A demo (Opção A) já traz um tour de primeiro
  acesso que explica cada tela e o porquê de cada decisão. Portar para a B (o
  dashboard real), guardando o "já vi" por usuário no backend em vez do
  `localStorage`, e com um passo a mais quando a autuação estiver disponível.
- **Dashboard mais completo.** O painel de hoje cobre o essencial do modo de
  triagem (priorização, revisão, nós, violações, métricas, auditoria). Evoluções
  previstas: visão consolidada por município (quando o multi-tenant entrar),
  série temporal de tendência, comparação entre pontos, e o mapa geográfico da
  seção 7. Nenhuma bloqueia o piloto; entram conforme o dado de campo justifica.
- **"Porquê" já entregue.** Cada evento agora mostra, na B e na demo, o motivo
  determinístico do nó (acionar/ambíguo/descartar) e o significado do status
  (pendente/confirmado/rejeitado) — a leitura em uma frase pedida na avaliação.
