# dashboard/ — painel do operador

Interface web servida pelo próprio backend. Sem etapa de build: HTML + CSS + JS.

## Dois perfis

| Perfil | O que vê e faz |
|---|---|
| Operador municipal | priorização, fila de revisão, histórico, exportação de relatório |
| Admin | tudo do operador + gestão de nós, versões de modelo, auditoria completa, alternância de modo |

## Telas

1. **Priorização** — tela inicial. Mapa de calor de onde e quando há mais
   ocorrências confirmadas, cruzado por hora do dia e dia da semana. É o
   entregável central em `modo=triagem`, e por isso vem antes da fila de
   revisão na hierarquia visual.
2. **Fila de revisão** — áudio, imagem, ângulo e score lado a lado, com
   confirmar/rejeitar.
3. **Nós** — status de cada sensor: online/offline, bateria, última captura,
   alertas de violação.
4. **Histórico** — busca e filtro de eventos já decididos.
5. **Métricas** — eventos por dia e local, taxa de rejeição ao longo do tempo.
6. **Modelo** — versões do classificador, performance de cada uma, reversão.
7. **Auditoria** — cadeia de hash com indicador claro de integridade.
8. **Configurações** — limiares, calibração por sensor, retenção, usuários e o
   alternador de modo (só admin).

## Identidade visual

| Uso | Fonte |
|---|---|
| Títulos | Manrope |
| Interface | Inter |
| Dados técnicos (dB, timestamps, hashes) | JetBrains Mono |

| Cor | Hex | Uso |
|---|---|---|
| Âmbar | `#F5A623` | pendente de revisão — evita vermelho, que sugere culpa antes da validação |
| Verde | `#2ECC71` | confirmado |
| Laranja Studio Cerne | `#FF6B35` | assinatura de marca, com moderação |
| Base | escuro editorial | seriedade institucional |

Interface densa em informação e legível. É ferramenta de uso diário de operador
municipal, não landing page.
