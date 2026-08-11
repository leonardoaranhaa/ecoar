# GUIA DE MONTAGEM E INTEGRAÇÃO — ECOA
## Do hardware solto ao sistema funcionando de ponta a ponta

Este guia assume que você já tem: os componentes de hardware comprados (seção 11
do manual técnico), o repositório criado (Prompt 0) e os módulos de código já
construídos via Claude Code (Prompts 1 a 11). Aqui é a parte física — montar,
conectar, e fazer o hardware "conversar" com o código que já existe.

---

## 1. FERRAMENTAS E ITENS DE APOIO (além do BOM)

Antes de começar, separe:

- Chave de fenda/phillips pequena, alicate de corte, estilete
- Multímetro (para conferir voltagem antes de ligar qualquer coisa na tomada)
- Cartão microSD (32GB+, classe 10) para o Raspberry Pi
- Cabo HDMI + teclado/mouse USB (só para a configuração inicial do Pi — depois
  disso, tudo é remoto via SSH)
- Um notebook/computador para gravar o cartão SD e acessar o Pi via SSH
- Fita isolante, abraçadeiras de nylon, e se possível uma caixa de teste (não
  precisa ser a caixa IP65 final ainda — essa é só para o MVP em bancada)

---

## 2. MAPA DE CONEXÕES FÍSICAS (visão geral)

```
                         ┌─────────────────────────┐
   4x Microfone MEMS ───►│                         │
   (ICS-43434, via I2S)  │                         │
                         │                         │
   Estação NMT ─────────┤   Raspberry Pi CM4      │──► Módulo 4G/LTE ──► Internet
   (mesmo poste, mesmo   │   (cérebro do sistema,  │    (Quectel EC25)
    conjunto; integração │   dentro de caixa IP65) │
    por rede ou serial)  │                         │
                         │                         │
   Câmera ANPR ─────────►│                         │
   (via USB ou CSI)      └─────────────────────────┘
                                    ▲
                                    │
                         Fonte 12V + bateria backup
```

**Importante — conjunto integrado, sem operador em campo:** o instrumento de
medição é uma **estação de monitoramento permanente (NMT)**, não um sonômetro
portátil de tripé. Ele é montado no mesmo poste, como parte do conjunto, com
gabinete próprio à prova de intempéries (IP65 de fábrica) e cápsula de
microfone projetada para fora com kit de proteção externa — a cápsula precisa
ficar exposta ao ar para medir, mas isso é parte do conjunto, como a lente de
uma câmera. A eletrônica do instrumento nunca é aberta ou embutida na caixa do
ECOAR: isso invalidaria a certificação. A integração é de **dados** (rede ou
porta digital), não mecânica. A caixa principal do ECOAR usa IP65, não IP68 —
vedação total impediria o som de chegar ao array MEMS.

Tudo converge no Raspberry Pi CM4 — ele é o único ponto que "conversa" com todos
os periféricos. O papel deste guia é garantir que cada seta acima vira uma
conexão física real e testada, uma de cada vez, antes de juntar tudo.

---

## 3. PASSO 1 — Preparar o Raspberry Pi CM4 (base de tudo)

1. Grave o Raspberry Pi OS (versão Lite, 64-bit) no cartão microSD usando o
   Raspberry Pi Imager, já configurando SSH, Wi-Fi (só para configuração inicial)
   e usuário/senha antes de gravar (o Imager tem essa opção em "configurações
   avançadas")
2. Insira o cartão, ligue o Pi (via fonte 12V com conversor para 5V, ou fonte USB-C
   separada nesta fase de bancada), e conecte via SSH do seu notebook:
   ```
   ssh usuario@<ip-do-pi>
   ```
3. Atualize o sistema:
   ```
   sudo apt update && sudo apt upgrade -y
   ```
4. Habilite as interfaces necessárias com `sudo raspi-config`:
   - Interface I2S (para os microfones MEMS)
   - Interface Serial (para o sonômetro e módulo 4G, se for via UART)
   - Interface Câmera (se a câmera ANPR for CSI; se for USB, não precisa)
5. Clone o repositório do projeto no Pi:
   ```
   git clone <seu-repositorio> ~/radar-sonoro
   cd ~/radar-sonoro
   ```
6. Instale as dependências de cada módulo conforme os `requirements.txt` gerados
   pelo Claude Code em cada pasta (`edge/audio_capture`, `edge/localization`,
   etc.) — recomenda-se criar um ambiente virtual único para todo o projeto:
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r edge/audio_capture/requirements.txt
   pip install -r edge/localization/requirements.txt
   pip install -r edge/classifier/requirements.txt
   # (repita para os demais módulos conforme forem sendo testados)
   ```

**Checkpoint 1:** você deve conseguir acessar o Pi via SSH e rodar `python3
--version` dentro do ambiente virtual sem erro, antes de seguir.

---

## 4. PASSO 2 — Conectar e testar o array de microfones MEMS (isoladamente)

1. Monte os 4 microfones ICS-43434 num suporte circular (pode ser impresso em 3D
   ou até um disco de plástico/madeira com furos espaçados igualmente — a
   geometria exata deve bater com o parâmetro configurado no módulo
   `edge/localization`)
2. Cada microfone I2S tem tipicamente 6 pinos: VDD, GND, WS (word select), SCK
   (clock), SD (data), e um pino de seleção de canal (L/R). Como você tem 4
   microfones e o Pi só tem uma interface I2S nativa, use um multiplexador de
   áudio I2S ou 4 placas ADC/I2S independentes conectadas via GPIO — **esse é o
   ponto mais delicado da montagem eletrônica; se você não tem experiência com
   solda/eletrônica, vale contratar um técnico local só para essa etapa
   específica, é rápido e barato**
3. Depois de conectado, rode o script de teste do módulo `edge/audio_capture`
   (gerado no Prompt 1) em modo de captura real (não simulação):
   ```
   python3 edge/audio_capture/main.py --mode=live --duration=10
   ```
4. Confirme que o script grava 4 canais de áudio simultâneos e calcula um valor
   de dB aproximado — bata palma perto de um microfone específico e veja se o
   canal correspondente mostra o pico mais alto

**Checkpoint 2:** os 4 canais gravam áudio distinto e sincronizado. Se só alguns
canais funcionam, o problema normalmente é conflito de endereço I2S entre os
microfones — revise a configuração de cada placa antes de seguir.

---

## 5. PASSO 3 — Integrar a estação de medição (NMT) ao conjunto

1. Escolha o equipamento conforme a fase do projeto: no piloto em
   `modo=triagem`, o array MEMS próprio já resolve e nenhuma NMT certificada é
   necessária. A NMT Classe 1 (ex: Svantek SV 307A/SV 303, Nanoenvi dB,
   Acoem/01dB, CRY2851) só é obrigatória em `modo=autuacao` — não antecipe esse
   custo
2. **Antes de comprar**, confirme com o fornecedor: (a) saída de dados digital
   documentada — rede, API ou porta serial; (b) recurso de autoverificação de
   calibração remota; (c) certificação e rastreabilidade metrológica inclusas
   no preço. Sem saída de dados documentada, não há como integrar
3. Monte a NMT no mesmo poste do conjunto ECOAR, usando o suporte do próprio
   fabricante. Não abra o invólucro nem remova peças — isso invalida a
   certificação
4. Posicione a cápsula do microfone com o kit de proteção externa instalado
   (anti-vento, anti-chuva, anti-pássaro), livre de obstruções e afastada de
   superfícies que gerem reflexão acústica
5. Faça a integração de dados. Se for por rede (caso mais comum em NMT), o
   Raspberry Pi consome os valores via API/protocolo do fabricante. Se for
   serial, identifique a porta:
   ```
   ls /dev/ttyUSB* /dev/ttyACM*
   ```
6. Implemente a classe específica do fabricante seguindo a interface
   `SonometroReader` criada no Prompt 1 — essa é a única parte do código que
   muda ao trocar de modelo de instrumento
7. Rode o script de leitura isolado:
   ```
   python3 edge/audio_capture/read_sonometro.py
   ```
8. Compare o valor lido via código com o valor reportado pela própria interface
   da NMT (painel web ou plataforma do fabricante) — devem bater exatamente

**Checkpoint 3:** o valor de dB lido via código bate com o valor reportado pela
plataforma do fabricante em pelo menos 5 medições diferentes (varie o volume do
ambiente para testar a faixa), e a autoverificação remota de calibração pode ser
acionada sem ninguém ir ao local.

---

## 6. PASSO 4 — Conectar e testar a câmera ANPR (isoladamente)

1. Conecte a câmera (USB ou CSI, conforme o modelo)
2. Teste a captura básica:
   ```
   python3 edge/camera_trigger/test_capture.py
   ```
3. Verifique se a imagem capturada tem resolução e enquadramento suficientes
   para ler uma placa a distância — teste com um carro/moto real estacionado na
   distância planejada de instalação (a mesma distância de detecção sonora, até
   15m conforme o manual técnico)
4. Rode o módulo de OCR de placa (`vision/plate_ocr`, se já construído) sobre a
   imagem capturada para confirmar que a leitura funciona na prática, não só em
   teoria

**Checkpoint 4:** a câmera captura uma placa legível na distância real de
instalação, de dia e à noite (teste com iluminação IR se o modelo tiver).

---

## 7. PASSO 5 — Conectar o módulo 4G/LTE (conectividade)

1. Insira o chip SIM no módulo Quectel EC25
2. Conecte ao Pi via USB
3. Configure a conexão de dados (normalmente via `ModemManager` ou `mmcli` no
   Raspberry Pi OS):
   ```
   sudo apt install modemmanager
   mmcli -L
   ```
4. Teste conectividade básica:
   ```
   ping -c 4 8.8.8.8
   ```

**Checkpoint 5:** o Pi tem acesso à internet via 4G, sem depender do Wi-Fi usado
na configuração inicial (desligue o Wi-Fi para confirmar que é o 4G mesmo
funcionando).

---

## 8. PASSO 6 — A PARTE DO "VENTRÍLOQUO": integrar tudo e fazer os módulos conversarem

Agora que cada peça funciona isoladamente (checkpoints 1-5), a integração é
literalmente conectar as saídas de um módulo às entradas do próximo, na ordem
que já está desenhada no código:

```
audio_capture (array MEMS + sonômetro)
        │
        ▼
localization (ângulo estimado a partir do array MEMS)
        │
        ▼
classifier (classifica o som: escapamento adulterado? buzina? outro?)
        │
        ▼
camera_trigger (decide: aciona câmera, ou marca como ambíguo)
        │
        ▼
vision (confirma tipo de veículo + lê placa, se câmera foi acionada)
        │
        ▼
evidence_packager (monta o pacote: áudio + dB do sonômetro + foto + ângulo +
                    score + hash)
        │
        ▼
ingestion_api (envia o pacote pro backend via 4G)
```

### Como testar essa cadeia inteira, passo a passo:

1. **Rode um script orquestrador** — se o Claude Code ainda não gerou um
   `main.py` na raiz do projeto que chama os módulos em sequência, peça a ele
   agora:
   ```
   No Claude Code: "Crie um script main.py na raiz do projeto radar-sonoro
   que orquestra o fluxo completo: audio_capture → localization → classifier →
   camera_trigger → vision → evidence_packager → ingestion_api, chamando cada
   módulo em sequência e passando a saída de um como entrada do próximo. Use
   logging detalhado em cada etapa para eu conseguir debugar qual módulo falhou
   se algo quebrar."
   ```
2. **Gere um evento de teste controlado**: com o sistema rodando, produza um som
   de escapamento real perto do array (ex: uma moto real passando, ou uma
   gravação tocada num alto-falante próximo) e observe o log de cada etapa:
   - O array captou e calculou o ângulo? (log da localization)
   - O classificador reconheceu como "escapamento adulterado" com que score?
     (log do classifier)
   - A câmera foi acionada? (log do camera_trigger)
   - A placa foi lida? (log da vision)
   - O pacote de evidência foi montado com todos os campos preenchidos,
     incluindo o dB do sonômetro certificado? (log do evidence_packager)
   - O pacote chegou no backend? (confira no `backend/ingestion_api`, olhando o
     banco SQLite ou a fila de revisão)
3. **Teste também o caminho de "não deveria acionar"**: produza um som que
   parece mas não é (buzina, ou apenas conversa alta) e confirme que o sistema
   NÃO aciona a câmera automaticamente, ou marca como "ambíguo" corretamente

**Checkpoint 6 (integração completa):** um evento real de teste percorre a
cadeia inteira, do som captado até aparecer na fila de revisão do dashboard,
com todos os dados corretos e nenhuma etapa pulada.

---

## 9. ERROS COMUNS NESSA FASE (e o que normalmente é)

| Sintoma | Causa provável |
|---|---|
| Áudio dos microfones cortado ou com ruído estranho | Alimentação elétrica instável — use fonte dedicada, não a mesma do Pi, para os microfones se possível |
| Ângulo de localização sempre errado, mesmo com áudio limpo | Geometria do array configurada no código não bate com a montagem física real — meça de novo com régua e corrija o parâmetro |
| Câmera aciona, mas a placa sai ilegível | Distância de instalação maior que o alcance do foco da lente, ou falta de iluminação IR à noite |
| Sonômetro não responde via serial | Baud rate errado no código (cada fabricante define um valor específico no manual do equipamento) |
| 4G conecta mas cai sozinho | Antena externa mal posicionada — pode ser necessário um cabo de antena mais longo até um ponto com melhor sinal no poste |
| Pacote de evidência chega incompleto no backend | Algum módulo está retornando erro silencioso — ative o logging detalhado sugerido no Passo 8 pra achar qual etapa falhou |

---

## 10. DEPOIS DA INTEGRAÇÃO FUNCIONANDO EM BANCADA

Só depois do Checkpoint 6 validado em bancada (mesa de teste, não still no poste
de rua) é que faz sentido partir para a instalação física real nos pontos
críticos de Bauru (Ponte São João, Centro), conforme o plano de MVP do manual
técnico (seção 10). Instalar direto na rua sem validar a cadeia completa em
bancada primeiro é o erro mais caro de se cometer nessa fase — qualquer ajuste
de código é muito mais rápido de fazer na mesa do que em cima de um poste.

---

*Este guia assume hardware genérico compatível com as especificações do manual
técnico. Ajustes de pinagem e protocolo variam por fabricante específico —
sempre confira o datasheet/manual do componente exato que você comprou antes de
conectar qualquer coisa à energia.*
