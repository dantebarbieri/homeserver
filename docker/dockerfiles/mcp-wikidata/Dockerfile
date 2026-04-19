FROM python:3.12-slim
ARG MCP_WIKIDATA_REF=v0.2.0
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt
RUN git clone --depth 1 --branch ${MCP_WIKIDATA_REF} https://github.com/zzaebok/mcp-wikidata.git
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e /opt/mcp-wikidata
COPY proxy.py start.sh ./
RUN chmod +x start.sh
EXPOSE 8080
CMD ["./start.sh"]
