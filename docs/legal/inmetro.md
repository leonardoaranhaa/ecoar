# MEDIÇÃO COM VALIDADE LEGAL — O QUE TRAVA O MODO DE AUTUAÇÃO

## Situação em agosto de 2026

Não existe regulamentação federal (Inmetro/CONTRAN) que valide juridicamente
multa automática por ruído veicular no Brasil. O sistema pioneiro de São José
dos Campos não confirmou emissão de multa válida; Curitiba testou sistema
semelhante desde 2022 e nunca multou.

Consequência direta no código: `modo=autuacao` existe, está implementado, e vem
**desligado**. `edge/config.py` recusa habilitá-lo sem declaração explícita de
base normativa e de instrumento certificado.

## O que o array MEMS do ECOAR é e não é

| | Array MEMS ICS-43434 (ECOAR) | Instrumento certificado (NMT Classe 1) |
|---|---|---|
| Para que serve | Localização direcional (GCC-PHAT) e classificação de assinatura acústica | Medição de nível sonoro com valor legal de prova |
| Norma | — | IEC 61672, todas as partes |
| Rastreabilidade metrológica | Não | Sim, com certificado |
| Necessário em `modo=triagem` | Sim | **Não** |
| Necessário em `modo=autuacao` | Sim | **Sim, obrigatório** |

O SPL calculado pelo array aparece em todo pacote de evidência com o campo
`valor_legal: false`. Isso não é ressalva de rodapé: é um campo do manifesto,
verificável por qualquer parte que receba o pacote.

## Categoria correta do instrumento: NMT, não sonômetro portátil

O produto pressupõe operação desassistida. Sonômetro portátil exige operador
presente com calibrador em campo, o que contraria o desenho. A categoria correta
é a estação de monitoramento permanente (Noise Monitoring Terminal), com:

- gabinete próprio à prova de intempéries (tipicamente IP65 de fábrica);
- autoverificação contínua de calibração e fonte sonora integrada para validação
  remota;
- saída de dados digital documentada (rede, API ou serial) — sem isso não há
  integração possível;
- certificação e rastreabilidade metrológica inclusas.

Exemplos de mercado: Svantek SV 307A / SV 303, Nanoenvi dB, Acoem/01dB, CRY2851.

Nota técnica relevante: o SV 307A foi a primeira estação de monitoramento de
ruído com microfone MEMS a receber aprovação Classe 1 do PTB, em conformidade
com a IEC 61672 — o que confirma que a tecnologia MEMS usada no array do ECOAR é
compatível com exigência metrológica de alto nível, desde que o conjunto inteiro
seja certificado.

**Operação desassistida não é manutenção zero.** Verificação metrológica
presencial periódica (tipicamente anual) continua sendo boa prática e deve
constar em contrato como manutenção programada.

## Os 4 sinais que reabrem essa decisão

Monitorar. Qualquer um disparando exige revisão do roteiro de fases:

1. Inmetro aprova modelo de instrumento acústico para fiscalização automática.
2. CONTRAN/SENATRAN publica norma específica sobre radar acústico.
3. Alguma cidade brasileira confirma multa válida por ruído, sem contestação
   bem-sucedida.
4. Sistema francês (LNE) é homologado e passa a multar.

## Como habilitar o modo de autuação quando houver base legal

Não basta trocar uma linha. O `edge/config.py` exige o bloco completo:

```yaml
modo: autuacao
autuacao:
  habilitada_por: "nome e cargo de quem autorizou"
  base_normativa: "norma federal que valida a autuação automática"
  instrumento_certificado:
    modelo: "..."
    classe: 1
    certificado: "número do certificado"
    validade_calibracao: "AAAA-MM-DD"
```

E o `SonometroReader` configurado precisa ser uma implementação real do
instrumento declarado, não o mock. Sem isso o nó não sobe.
