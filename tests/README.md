# tests/

`pytest` na raiz do repositório. A suíte roda inteira numa máquina comum, sem
nenhum componente de hardware — é o teste da decisão D11.

Cobertura obrigatória, por módulo:

- **localization**: ângulo estimado a partir de sinal sintético bate com o
  ângulo conhecido, dentro da margem declarada;
- **evidence_packager**: alterar qualquer campo ou byte de mídia depois de
  gerado muda o hash e faz a verificação falhar;
- **camera_trigger**: a tabela de decisão produz a mesma saída para a mesma
  entrada, e cai em `ambiguo` quando um subsistema está indisponível;
- **audit_log**: a cadeia de hash detecta remoção ou alteração de qualquer
  entrada do histórico;
- **config**: `modo=autuacao` sem declaração completa recusa iniciar.

Regra: módulo do caminho de decisão sem teste não entra.
