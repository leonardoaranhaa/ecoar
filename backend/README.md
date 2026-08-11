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
