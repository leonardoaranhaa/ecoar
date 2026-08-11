# backend/training_pipeline — re-treino do classificador

Só faz sentido depois de haver volume real de eventos confirmados por operador
humano. Antes disso, não há o que treinar.

## Dois riscos que o desenho neutraliza

**Esquecimento catastrófico** — re-treinar só com dado novo piora o modelo em
casos antigos que já acertava. Mitigação: todo dataset de re-treino é mistura de
dado novo confirmado + amostra fixa do histórico. Nunca substituição total.

**Viés autoalimentado** — se o modelo erra de forma sistemática e ninguém
corrige, ele aprende o próprio erro. Mitigação: nenhuma captura bruta vira
treino; apenas o que um humano confirmou.

## Ciclo

```
eventos confirmados desde o último ciclo
  + amostra fixa do histórico
  → re-treino em lote (semanal, nunca em tempo real)
  → avaliação contra conjunto de validação fixo e separado
  → promove a produção SOMENTE se não piorou
  → registra: quantos eventos entraram, performance antes/depois, promovido ou não
```

Cada ciclo é uma versão de modelo, reversível pelo dashboard.
