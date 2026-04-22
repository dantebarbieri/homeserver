FROM python:3.14-slim
# zzaebok/mcp-wikidata has no tags; pin to a known-good master SHA.
ARG MCP_WIKIDATA_REF=af04e601f8f8800d455fd280ac4e877165b7c2f8
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt
RUN git clone https://github.com/zzaebok/mcp-wikidata.git \
    && git -C mcp-wikidata checkout ${MCP_WIKIDATA_REF}
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e /opt/mcp-wikidata
COPY proxy.py start.sh ./
RUN chmod +x start.sh
EXPOSE 8080
CMD ["./start.sh"]
