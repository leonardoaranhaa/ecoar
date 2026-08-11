# LGPD — MINIMIZAÇÃO, RETENÇÃO E FINALIDADE

A placa de um veículo é dado pessoal: identifica o proprietário via consulta ao
Detran. Imagem e áudio captados em via pública também. O desenho do ECOAR trata
isso na arquitetura, não em política escrita depois.

## Minimização por desenho

1. **O nó de borda não lê placa.** Não há OCR no `edge/`. A imagem é capturada e
   enviada; a leitura só acontece no backend, sob demanda, e apenas quando o modo
   de operação exigir.
2. **Em `modo=triagem` a placa não é lida nem armazenada em texto.** Priorização
   de fiscalização responde "onde e quando", não "quem". Nenhuma etapa da
   triagem precisa identificar o veículo.
3. **Enquadramento evita o condutor.** A câmera é posicionada para capturar
   placa e veículo, não o rosto de quem conduz. Isso é procedimento de
   instalação — ver `docs/hardware/instalacao.md`.
4. **Nada de valor pessoal em log.** O log registra que um evento ocorreu, o
   score, o ângulo e o identificador do evento. Nunca conteúdo de placa.

## Finalidades distintas, retenções distintas

Guardar mídia para virar dado de treino é finalidade **diferente** de produzir
prova de ocorrência. Cada uma tem prazo próprio, declarado na configuração do
nó e aplicado pelo backend:

| Finalidade | O que retém | Prazo padrão | Onde configura |
|---|---|---|---|
| Triagem/priorização | Metadado do evento (sem mídia) | 730 dias | `retencao.metadado_dias` |
| Evidência de evento pendente | Áudio + imagem | 30 dias | `retencao.midia_pendente_dias` |
| Evidência de evento confirmado | Áudio + imagem | 180 dias | `retencao.midia_confirmada_dias` |
| Evento rejeitado | — (mídia apagada) | 7 dias | `retencao.midia_rejeitada_dias` |
| Dado de treino | Áudio anonimizado | 1095 dias | `retencao.treino_dias` |

Regras que o expurgo aplica:

- evento **rejeitado** perde a mídia rápido: não virou prova nem vira treino;
- áudio promovido a dado de treino é copiado para o acervo de treino **sem** a
  imagem associada e sem identificador de veículo;
- metadado sobrevive à mídia — o mapa de calor continua válido depois de a
  imagem ter sido expurgada, o que é justamente o ponto de reter menos.

## Titular e contestação

Qualquer pessoa autuada (quando e se o modo de autuação for habilitado) precisa
de caminho claro para obter o pacote de evidência do próprio evento. O pacote é
autocontido e verificável: `python -m edge.evidence_packager.verificar
<arquivo>.ecoar` confere todos os hashes sem depender do nosso sistema.

## O que este documento não é

Não é declaração de conformidade. O ECOAR entrega controle técnico e trilha de
evidência; a decisão sobre bases legais de tratamento, RIPD e prazos definitivos
é do encarregado de dados do município contratante.
