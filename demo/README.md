# demo/ — demonstração de produto (Opção A)

Página **self-contained** para a reunião de produto: um único arquivo, dado de
exemplo embutido, mapa esquemático em SVG, áudio sintetizado no navegador. Abre
por duplo-clique, **sem servidor e sem internet** — inclusive no celular.

```
demo/index.html   # abra no navegador
```

Publicada também como Artifact (link compartilhável) — ver o PR #2.

## O que ela mostra

- **Login-lite:** escolhe cidade + papel (operador/admin), sem senha, rotulado
  "demonstração".
- **3 cidades** (Bauru, Piracicaba, Marília) — o seletor troca todo o dado.
- **Mapa** com os equipamentos, cor pelo estado, clique abre o detalhe do nó.
- **Priorização** — mapa de calor hora × dia da semana + ranking de pontos.
- **Fila de revisão** — evento com áudio (sintetizado), regras avaliadas pelo
  nó, e confirmar/rejeitar. Mostra os três desfechos: acionar, ambíguo,
  descartar (a buzina que o sistema **não** aciona — o anti-falso-positivo).
- **Auditoria** (papel admin) — a trilha hash-chain com indicador de integridade.

## O que ela NÃO é

Um mockup navegável com **dado de exemplo**. Não lê placa, não gera multa, o SPL
não tem valor legal, e o mapa é esquemático (não geográfico). É honesta sobre
isso em cada tela — é o que dá credibilidade na primeira pergunta técnica.

O sistema de verdade é o `backend/` + `dashboard/`; esta demo reaproveita a
identidade visual dele, mas roda sozinha, sem backend.
