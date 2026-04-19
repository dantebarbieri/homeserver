FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY proxy.py start.sh ./
RUN chmod +x start.sh
EXPOSE 8080
CMD ["./start.sh"]
