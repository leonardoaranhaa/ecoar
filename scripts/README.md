# scripts/ — utilitários de bancada

Ferramentas de apoio para desenvolvimento, montagem e demonstração. Nada aqui
roda em produção.

Previstos ao longo da construção:

- geração de áudio sintético multicanal a partir de um ângulo conhecido, para
  validar a localização sem hardware;
- ensaio ponta a ponta: do som simulado até o evento aparecer na fila de revisão
  do dashboard;
- verificação independente de um pacote de evidência;
- teste isolado de cada periférico, usado nos checkpoints de
  `docs/hardware/README.md`.

## `semear_demo.py` — a demo da reunião de produto (Opção B)

Semeia o backend **real** com o cenário de Piracicaba (cinco pontos do
levantamento em `docs/field-notes/piracicaba.md`),
para mostrar o sistema rodando de verdade numa reunião — não um mock de tela.

Cada evento é um pacote `.ecoar` montado pelo mesmo código do nó, enviado pela
API de ingestão real (o hash é revalidado na entrada) e decidido pela fila de
revisão real (a trilha de auditoria encadeia cada decisão). Ao final há eventos
confirmados, rejeitados e pendentes, heartbeats, um nó fora do ar e um alerta
patrimonial — tudo pelo caminho de código de produção.

```bash
python -m scripts.semear_demo --config config/backend.demo.yaml --recriar
python -m backend.cli --config config/backend.demo.yaml
# abra http://127.0.0.1:8000/  — token operador ou admin de config/backend.demo.yaml
```

A semente é fixa: mesmo comando, mesmo banco. Os tokens da `backend.demo.yaml`
trazem padrão embutido só para a demo subir sem exportar variável — é banco de
brinquedo, não vale para produção (ver o cabeçalho do arquivo).

O que a demo mostra: **um backend atendendo várias instalações** — a fundação do
multi-tenant. O isolamento por município (login por cidade) é a fase seguinte,
planejada em `docs/arquitetura-multicidade.md`.
