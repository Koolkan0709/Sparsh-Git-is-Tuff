FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UDP_PORT=0
COPY server.py ./
COPY public ./public
EXPOSE 10000
CMD ["python", "server.py"]
