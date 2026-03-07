IMAGE_NAME = kick_analytics
PORT_CONTAINER = $${PORT:-8080}
PORT_HOST = 8000

info:
	@echo "🚀 KickAnalytics - Usage Guide"
	@echo ""
	@echo "📋 INSTALLATION (one time only) :"
	@echo "   make install-docker    # Install Docker + restart terminal"
	@echo ""
	@echo "🧪 LOCAL TESTING :"
	@echo "   make test              # Build + run app → http://localhost:8000"
	@echo ""
	@echo "☁️  GOOGLE CLOUD DEPLOYMENT :"
	@echo "   1. Configure .env with the PROJECT_ID"
	@echo "   2. make gcloud-auth    # Authenticate Google Cloud (once)"
	@echo "   3. make deploy-gcloud  # Deploy → Google displays final URL"
	@echo ""
	@echo "🧹 CLEANUP :"
	@echo "   make clean"

test: build run-local

install-docker:
	sudo apt update
	sudo apt install docker.io
	sudo systemctl start docker
	sudo systemctl enable docker
	sudo usermod -aG docker $$USER
	@echo "Restart your terminal or run: newgrp docker"

build:
	docker build -t $(IMAGE_NAME) .

# localhost:8000 -> container:8080 (server is listening on 8080)
run-local:
	docker run -p $(PORT_HOST):$(PORT_CONTAINER) $(IMAGE_NAME)

gcloud-auth:
	gcloud auth login
	gcloud config set project $(PROJECT_ID)

deploy-gcloud:
	gcloud builds submit --tag gcr.io/$${PROJECT_ID}/$(IMAGE_NAME)
	gcloud run deploy $(IMAGE_NAME) \
		--image gcr.io/$${PROJECT_ID}/$(IMAGE_NAME) \
		--platform managed \
		--region europe-west1 \
		--allow-unauthenticated

clean:
	docker rmi $(IMAGE_NAME) || true
	docker system prune -f

.PHONY: info test install-docker build run-local gcloud-auth deploy-gcloud clean