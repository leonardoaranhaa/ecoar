# edge/evidence_packager — o pacote de evidência

Monta, para cada evento, um arquivo único, autocontido e verificável. É o que
transforma uma detecção em algo que resiste a contestação.

## Conteúdo de cada pacote

- áudio bruto, 10 s antes e 10 s depois do pico (do buffer do `audio_capture`);
- SPL estimado pelo array, com a referência da calibração usada e a marcação
  `valor_legal: false`;
- leitura do instrumento certificado, quando presente (`modo=autuacao`);
- imagem da placa e imagem panorâmica, quando a câmera foi acionada;
- ângulo de chegada estimado e sua confiança;
- timestamp sincronizado por NTP e geolocalização fixa do nó;
- classe prevista e score do classificador, com a versão do modelo;
- versão da política de decisão que gerou o acionamento;
- modo de operação vigente no momento da captura.

## Integridade

Cada arquivo de mídia entra no manifesto com seu próprio SHA-256. O manifesto é
serializado de forma canônica (chaves ordenadas) e recebe um hash próprio.
Qualquer alteração posterior em qualquer campo ou byte de mídia muda o hash — e
a verificação falha.

A verificação não depende do nosso sistema: o pacote é um zip com um JSON
dentro, e existe um comando de verificação independente. Quem recebe o pacote
consegue conferir sozinho.

## O que **não** entra no pacote

Nenhum texto de placa. O nó não lê placa (decisão D10). A imagem vai; a
identificação do veículo, se e quando ocorrer, acontece no backend, sob a
política de retenção de `docs/legal/lgpd.md`.

## Como a integridade funciona

Cada arquivo de mídia entra no manifesto com o seu próprio SHA-256, e o
manifesto inteiro recebe um hash calculado sobre a sua forma canônica. Alterar
um byte de áudio muda o hash do áudio, que está dentro do manifesto, que muda o
hash do manifesto. **Um número no fim da cadeia protege tudo.**

Canônico significa chaves ordenadas, sem espaço supérfluo, UTF-8. Sem isso,
reserializar o mesmo conteúdo produziria bytes diferentes e a verificação
falharia por um motivo que não é adulteração — e um verificador que dá alarme
falso deixa de ser usado.

O que a verificação detecta, cada um com teste próprio:

| Adulteração | Como é pega |
|---|---|
| campo do manifesto alterado | hash do manifesto não confere |
| byte de áudio ou imagem alterado | hash do arquivo não confere |
| mídia removida do pacote | arquivo declarado e ausente |
| mídia **injetada** no pacote | arquivo presente e não declarado |
| pacote corrompido | zip inválido, sem derrubar o verificador |

## Verificar

```bash
python -m edge.evidence_packager.verificar evento.ecoar
```

```
evento ......... evt-demo
nó ............. bauru-ponte-sao-joao-01
modo ........... triagem
decisão ........ acionar (politica/1.0)
classificação .. escapamento_adulterado score 0.92 [heuristico 1.0]
ângulo ......... 12.0° ±2.0° (confiança 0.95)
SPL estimado ... 84.97 dB — valor legal: NÃO
imagens ........ 2
hash ........... sha256:87ce8a30...

INTEGRIDADE: íntegro — nenhum byte foi alterado desde a geração
```

Saída 0 = íntegro, 1 = alterado. O comando **não consulta banco, não acessa
rede e não depende de chave nossa**: ele existe para ser rodado por quem não é
nós — a prefeitura, o advogado do autuado, um perito.

## Formato

`.ecoar` é um zip com `evento.json` (o manifesto) e `midia/`. Sem formato
proprietário: qualquer pessoa abre com um descompactador comum e lê o JSON.

## O que o manifesto diz sobre o que ele **não** é

Três campos existem para impedir que o pacote seja lido como mais do que é:

- `spl_estimado.valor_legal: false` — o array MEMS não mede com valor de prova;
- `leitura_de_placa.realizada: false` com o motivo — a ausência é decisão de
  arquitetura (D10), não esquecimento;
- `aviso_legal` — registra ocorrência para triagem, não constitui auto de
  infração.
