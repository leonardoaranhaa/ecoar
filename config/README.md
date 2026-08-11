# config/ — configuração por nó

Cada nó instalado tem um arquivo de configuração próprio: identificação,
geolocalização fixa, geometria real do array (medida com régua na montagem),
calibração de SPL, limiares de decisão, endereço do backend e política de
retenção.

Nada disso é constante de código. Dois nós no mesmo município podem ter
limiares diferentes — uma via de tráfego pesado tem piso de ruído diferente de
uma rua residencial.

**Segredos não moram aqui.** Token de uplink e credenciais vêm de variável de
ambiente. O arquivo de exemplo versionado nunca contém valor real.

O carregador de configuração é fail-closed: configuração inválida aborta a
inicialização do nó, e `modo=autuacao` exige declaração explícita de base
normativa e instrumento certificado (`docs/legal/inmetro.md`).
