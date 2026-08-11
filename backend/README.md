# backend/ — nuvem

Recebe os pacotes dos nós, guarda, organiza a revisão humana e serve o
dashboard. Hospedagem em território nacional.

## Módulos

| Pasta | Papel |
|---|---|
| `ingestion_api/` | recebe pacotes via HTTPS, revalida o hash, armazena, cria o evento com status `pendente_revisao` |
| `review_queue/` | fila de revisão humana: lista, confirma, rejeita |
| `training_pipeline/` | re-treino em lote, só com dado confirmado por operador |
| `audit_log/` | trilha de auditoria encadeada por hash |

## Regras estruturais

- **Todo evento entra como `pendente_revisao`.** Não existe caminho de código
  que crie um evento já confirmado (decisão D2).
- **Hash revalidado na entrada.** Pacote cujo hash não bate é rejeitado como
  corrompido ou adulterado em trânsito, e a rejeição também vai para a
  auditoria.
- **Acesso a pacote de evidência é auditado.** Quem abriu, qual evento, quando.
- **SQLite no MVP, com acesso isolado em `backend/db.py`.** Trocar por Postgres
  não deve tocar nenhum módulo de negócio.

## Rodar

```bash
export ECOAR_TOKEN_NO_01=$(openssl rand -hex 24)
export ECOAR_TOKEN_OPERADOR=$(openssl rand -hex 24)
export ECOAR_TOKEN_ADMIN=$(openssl rand -hex 24)

python -m backend.cli --config config/backend.exemplo.yaml --porta 8000
```

O painel do operador fica em `http://localhost:8000/`, a documentação da API em
`/docs`.

## Rotas

| Rota | Quem usa | O que faz |
|---|---|---|
| `POST /v1/eventos` | nó | envia o pacote `.ecoar`; o hash é revalidado aqui |
| `POST /v1/heartbeat` | nó | sinal de vida com bateria e saúde |
| `GET /v1/eventos` | operador | fila, com filtro por status e por nó |
| `GET /v1/eventos/{id}` | operador | detalhe com o manifesto inteiro |
| `POST /v1/eventos/{id}/revisao` | operador | confirmar, rejeitar ou (só em autuação) confirmar multa |
| `GET /v1/eventos/{id}/midia/{nome}` | operador | mídia servida de dentro do pacote |
| `GET /v1/eventos/{id}/audio-audicao.wav` | operador | mono 16 bits, só para ouvir |
| `GET /v1/nos` | operador | estado dos sensores |
| `GET /v1/saude` | público | resumo da fila |

## Quatro garantias da ingestão

1. **O hash é revalidado no backend.** Confiar no que o nó afirma sobre a
   própria evidência esvaziaria a cadeia de custódia.
2. **Todo evento entra como `pendente_revisao`.** `inserir_evento` nem aceita
   status como parâmetro — passar `confirmado` não tem efeito, e existe teste
   para isso.
3. **Rejeição não é silenciosa.** Pacote recusado vai para a tabela `rejeicoes`
   com o motivo. É o registro que mostra corrupção em trânsito ou tentativa de
   adulteração.
4. **Reenvio é idempotente.** O nó só apaga o pacote da fila local depois da
   confirmação; se ela se perder no 4G, ele reenvia. Reenvio não pode virar
   evento duplicado na fila do operador.

Além disso: o token autentica um nó, e o manifesto precisa declarar **o mesmo**
nó. Um nó não envia evento em nome de outro.

## Trava de modo

`confirmar_multa` só é aceito se o evento tiver sido **capturado** em
`modo=autuacao`. O modo viaja dentro do pacote; um evento capturado em triagem
não pode ser reclassificado como autuação depois que o modo mudar. Sem essa
trava, a evidência não sustentaria a autuação.

## Mídia

A mídia nunca é desempacotada para disco: sai do zip direto para a resposta.
Cópia solta fora do pacote é cópia sem hash — e a primeira pergunta de uma
contestação é de onde veio aquele arquivo.

Só nomes declarados no manifesto são servidos. O nome vem da URL, e aceitar
qualquer um deixaria a URL escolher o arquivo dentro do zip.

O áudio tocado no painel é uma conversão mono de 16 bits, **e o painel diz
isso**. A evidência é o áudio de 4 canais e 24 bits dentro do pacote, que é o
que o hash protege.

## Dívida registrada, não esquecida

Token estático entre nó e backend é suficiente para o MVP e insuficiente para
operação contratada. Antes do contrato: certificado por nó (mTLS).
