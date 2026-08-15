# deploy/ — a demo da Opção B rodando num VPS

Sobe o **sistema real** do ECOAR (backend + painel), semeado com o cenário de Piracicaba,
num servidor acessível pela internet. É o que você leva para uma reunião de
produto quando a plateia é técnica e a pergunta é "mostra funcionando".

Não confundir com a **Opção A** (`demo/`), que é uma página self-contained sem
servidor. Esta aqui é o produto de verdade, com ingestão, fila de revisão e
trilha de auditoria reais.

## O que sobe

- um contêiner só, com FastAPI + SQLite (o mesmo backend da etapa 11);
- semeado no primeiro boot com 5 pontos de Piracicaba (tirados do levantamento
  em `docs/field-notes/piracicaba.md`), ~193 eventos enviados pela API real,
  confirmados por operador, um nó fora do ar e um alerta patrimonial;
- painel em `http://SEU_IP:8000/`.

Acesso por **IP:porta**, protegido por token forte. Sem domínio, sem HTTPS —
proposital, para subir rápido. A seção final mostra como colocar domínio e
cadeado se você quiser um link limpo.

## Escolha do VPS (território nacional — regra do projeto)

A hospedagem do ECOAR é em território nacional (ver `CLAUDE.md`). Para a demo,
qualquer VPS pequeno serve; a demo cabe em 1 vCPU / 1 GB de RAM.

| Provedor | Observação |
|---|---|
| **Magalu Cloud** | nuvem nacional, datacenter no Brasil — o mais alinhado ao discurso de soberania do produto |
| **Hostinger (BR)** | VPS barato com região de São Paulo, painel simples |
| **KingHost / Locaweb** | nacionais tradicionais, bom quando o cliente já é cliente deles |

Pegue uma imagem **Ubuntu 22.04 ou 24.04**. Anote o IP público.

> Para a **reunião**, um VPS é o certo. Se for só um teste no seu notebook, pule
> o VPS e rode o mesmo `docker compose up` localmente — o acesso vira
> `http://127.0.0.1:8000/`.

## Passo a passo (do zero ao painel no ar)

Tudo como root (ou com `sudo`), numa sessão SSH no VPS recém-criado.

### 1. Instalar Docker

```bash
curl -fsSL https://get.docker.com | sh
```

### 2. Trazer o código

```bash
apt-get update && apt-get install -y git
git clone https://github.com/leonardoaranhaa/ecoar.git
cd ecoar
# enquanto a Opção B não estiver na main, use a branch da PR:
git checkout claude/ecoar-mvp-hardware-u3fkk0
cd deploy
```

### 3. Gerar os tokens fortes

```bash
./gerar-env.sh
```

Ele cria `deploy/.env` com dez tokens aleatórios de 128 bits e **imprime os dois
que interessam** — o do operador e o do admin. Guarde-os: são a senha de login
do painel na reunião. (O `.env` nunca vai para o Git.)

### 4. Subir

```bash
docker compose up -d
```

O primeiro boot constrói a imagem e **semeia o cenário de Piracicaba** — leva um ou dois
minutos. Acompanhe:

```bash
docker compose logs -f
```

Quando aparecer `Uvicorn running on http://0.0.0.0:8000`, está no ar.

### 5. Abrir o firewall na porta 8000

A maioria dos VPS bloqueia portas altas por padrão. Libere a 8000 no painel do
provedor (grupo de segurança / firewall) e, se o Ubuntu estiver com `ufw` ligado:

```bash
ufw allow 8000/tcp
```

### 6. Acessar

No navegador: `http://SEU_IP:8000/`. Cole o token do operador (ou o do admin,
que também vê **Modelo** e **Auditoria**). Pronto — priorização, nós, revisão e a
trilha de auditoria, com o cenário de Piracicaba.

## Operação

```bash
docker compose logs -f          # ver o que está acontecendo
docker compose restart          # reiniciar (preserva o banco e as decisões)
docker compose down             # parar (o volume com os dados fica)
docker compose down -v          # parar E apagar os dados (recomeça do zero no próximo up)
```

O banco, os pacotes e a trilha de auditoria vivem num volume Docker
(`ecoar-dados`). Reiniciar o contêiner **não** re-semeia nem apaga o que o
operador decidiu — o seed só roda quando o banco não existe.

## Um lembrete honesto para a reunião

Vale o mesmo rótulo da Opção A: o dado é **semeado para a demonstração**, não é
captura de campo. O sistema não lê placa, não gera multa e não mede dB com valor
legal. O que a demo prova é a **plataforma** — ingestão com hash revalidado,
validação humana obrigatória, priorização sobre evento confirmado e trilha
auditável — e a **fundação do multi-tenant**: um backend atendendo várias
instalações. O isolamento por município (login por cidade) é a fase seguinte,
descrita em `docs/arquitetura-multicidade.md`.

## Domínio e cadeado (opcional, para um link limpo)

Se quiser `https://ecoar-demo.seudominio.br` em vez de `http://IP:8000`, ponha um
proxy reverso com TLS automático na frente. O caminho mais curto é o Caddy:

1. aponte um registro A do seu domínio para o IP do VPS;
2. no `docker-compose.yml`, troque `ports: ["8000:8000"]` por `expose: ["8000"]`
   (o serviço deixa de publicar direto);
3. suba um Caddy ao lado com um `Caddyfile` de duas linhas:

   ```
   ecoar-demo.seudominio.br {
       reverse_proxy ecoar:8000
   }
   ```

O Caddy emite e renova o certificado Let's Encrypt sozinho. Fica para quando a
demo virar piloto — para a reunião, IP:porta basta.
