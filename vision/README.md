# vision/ — visão computacional

**Complementar ao áudio, nunca substituto.** A decisão de que houve uma
ocorrência vem do áudio (`edge/classifier` + `edge/localization`). A visão
computacional confirma e desambigua.

Esta camada só entra depois que a parte de áudio estiver validada em campo — não
faz sentido gastar esforço de visão em eventos que o áudio já descartaria.

| Pasta | Papel |
|---|---|
| `vehicle_type/` | confirma que o veículo no quadro é de fato uma motocicleta, antes de aceitar a captura como válida |
| `plate_ocr/` | dois pipelines de OCR independentes; a leitura só é aceita se ambos concordarem |
| `trajectory/` | cruza a trajetória detectada por imagem com o ângulo estimado pelo array, para decidir qual veículo é a fonte real quando dois passam juntos |

Roda no backend, não no nó (decisão D10): o nó não lê placa. Em `modo=triagem`,
`plate_ocr` permanece desligado — priorização responde "onde e quando", não
"quem".
