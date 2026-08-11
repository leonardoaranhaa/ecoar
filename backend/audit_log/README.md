# backend/audit_log — trilha de auditoria

Registra, em cadeia encadeada por hash:

- cada evento recebido pela ingestão (e cada pacote rejeitado, com o motivo);
- cada ação de revisão humana: quem confirmou ou rejeitou, quando;
- cada ciclo de re-treino e cada promoção ou reversão de modelo;
- cada acesso ao pacote de evidência de um evento específico;
- cada alerta de violação patrimonial;
- cada troca de modo de operação.

## Hash-chain

Cada entrada inclui o hash da entrada anterior. Alterar ou remover qualquer
entrada do histórico quebra a cadeia a partir dali, e a quebra é detectável por
qualquer pessoa que rode a verificação — inclusive a defesa de um autuado.

É isso que separa "temos um log" de "temos uma trilha que resiste a
contestação".

## Regra de conteúdo

A trilha registra **que** algo aconteceu, com identificador de evento, operador
e timestamp. Ela não duplica conteúdo de mídia nem armazena texto de placa.

## Como a cadeia funciona

Cada entrada inclui o hash da entrada anterior, e o seu próprio hash cobre todos
os campos — inclusive esse ponteiro para trás. Alterar qualquer campo de uma
entrada muda o hash dela; como esse hash é o `hash_anterior` da seguinte, a
quebra se propaga até o fim. Remover uma entrada abre um salto na sequência.
Reordenar quebra os elos. Nenhuma dessas operações passa pela verificação.

A âncora é fixa e conhecida (`GENESE`, 64 zeros), para que a verificação saiba
onde a cadeia começa e possa ser reproduzida por terceiros.

## O que é registrado

| Tipo | Quando | Ator |
|---|---|---|
| `evento_recebido` | ingestão aceita um pacote | o nó |
| `evento_rejeitado` | pacote recusado, com o motivo | o nó |
| `revisao` | operador confirma ou rejeita | o operador |
| `acesso_evidencia` | alguém abre a mídia de um evento | quem abriu |
| `alerta_violacao` | violação patrimonial | o nó |
| `troca_de_modo` | triagem ↔ autuação | quem trocou |
| `retreino` | ciclo de re-treino (etapa 9) | o sistema |

## Atomicidade

`registrar()` não faz commit próprio. Quando chamado dentro de uma transação de
negócio — ingestão, revisão — a entrada de auditoria e a mudança de estado são
atômicas: ou as duas acontecem, ou nenhuma. Um evento gravado sem trilha, ou uma
trilha apontando para um evento que não existe, seriam piores que nenhum log.

## Regra de conteúdo (D6)

A trilha registra **que** algo aconteceu, com identificador de evento, ator e
timestamp — nunca conteúdo de placa. `registrar()` recusa, com erro, qualquer
campo de detalhe que se pareça com dado pessoal (`placa`, `condutor`, `cpf`…).
Dado pessoal na trilha é erro de programação, não dado a ser guardado.

## Verificar

```
GET /v1/auditoria/verificar     (só admin)
```

```json
{"integra": true, "total": 42, "resumo": "cadeia íntegra: 42 entradas encadeadas"}
```

A verificação não depende de nada externo: lê as entradas em ordem, refaz cada
hash e confere os elos.
