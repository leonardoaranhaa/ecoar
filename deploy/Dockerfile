# Imagem do backend ECOAR para a demonstração em VPS.
#
# Só o núcleo (requirements.txt): FastAPI, uvicorn, numpy, PyYAML, httpx. Sem
# torch e sem dependência de hardware — o backend não importa nenhuma delas, e
# a imagem fica pequena. O seed usa o mesmo código do nó, que só precisa de
# numpy.
FROM python:3.11-slim

WORKDIR /app

# Dependências primeiro, para o cache do Docker não reinstalar a cada mudança
# de código.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# O código. dados/ fica de fora (é volume) e vem no .dockerignore.
COPY backend/ ./backend/
COPY edge/ ./edge/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh

RUN chmod +x deploy/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./deploy/entrypoint.sh"]
