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

# ignored by google cloud build, but needed for local testing
EXPOSE 8080

CMD ["python", "server.py"]