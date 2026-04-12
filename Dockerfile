FROM python:3.9-slim
# Starting point for Docker image, based on Python 3.9 slim
# instead of :
#     sudo apt update
#     sudo apt install python3
#     sudo apt install pip
#     pip install requirements.txt

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python3 quantize_model.py

# ignored by google cloud build, but needed for local testing
# 8080 : HTTP fichiers statiques
# 8081 : WebSocket
EXPOSE 8080
EXPOSE 8081

CMD ["python", "-u", "server.py"]