IMAGE_NAME   = kick-analytics
HTTP_PORT    = 8080
-include .env
export

info:
	@echo "🚀 KickAnalytics - Usage Guide"
	@echo ""
	@echo "📋 INSTALLATION (one time only) :"
	@echo "   make install-docker    # Install Docker + restart terminal"
	@echo "   make install-ngrok     # Install ngrok + add authtoken"
	@echo "   make install-gcloud    # Install Google Cloud SDK"
	@echo ""
	@echo "🧪 LOCAL TESTING :"
	@echo "   make test              # Build + run app -> http://localhost:$(HTTP_PORT)"
	@echo ""
	@echo "📱 LOCAL TESTING WITH PHONE :"
	@echo "   1. make test           # Terminal 1 — start container"
	@echo "   2. make tunnel         # Terminal 2 — expose to phone"
	@echo ""
	@echo "☁️  GOOGLE CLOUD DEPLOYMENT :"
	@echo "   1. Configure .env with the PROJECT_ID"
	@echo "   2. make install-gcloud # Install Google Cloud SDK"
	@echo "   3. make gcloud-auth    # Authenticate Google Cloud (once)"
	@echo "   4. make deploy-gcloud  # Deploy -> Google displays final URL"
	@echo ""
	@echo "🧹 CLEANUP :"
	@echo "   make clean"

test: build
	ENV=development $(MAKE) run-local

install-docker:
	sudo apt update
	sudo apt install docker.io
	sudo systemctl start docker
	sudo systemctl enable docker
	sudo usermod -aG docker $$USER
	@echo "Restart your terminal or run: newgrp docker"

install-ngrok:
	curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
	| sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
	&& echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
	| sudo tee /etc/apt/sources.list.d/ngrok.list \
	&& sudo apt update \
	&& sudo apt install ngrok
	@echo "Run: ngrok config add-authtoken <token>"

install-gcloud:
	curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts
	@echo "Run: source ~/.bashrc"

build:
	docker build -t $(IMAGE_NAME) .

run-local:
	docker run -p $(HTTP_PORT):8080 --memory=2g --env-file .env -e ENV=$${ENV} $(IMAGE_NAME)

tunnel:
	ngrok http $(HTTP_PORT)

check-gcloud:
	@export PATH="$$HOME/google-cloud-sdk/bin:$$PATH"; \
	command -v gcloud >/dev/null 2>&1 || { \
		echo "gcloud CLI not found. Run: make install-gcloud"; \
		exit 127; \
	}

gcloud-auth: check-gcloud
	PATH="$$HOME/google-cloud-sdk/bin:$$PATH" gcloud auth login
	PATH="$$HOME/google-cloud-sdk/bin:$$PATH" gcloud config set project $${PROJECT_ID}

configure-gcloud:
	gcloud run services update $(IMAGE_NAME) \
		--region europe-west1 \
		--cpu 4 \
		--memory 4Gi \
		--min-instances 1 \
		--max-instances 1 \
		--timeout 3600 \
		--no-cpu-throttling

deploy-gcloud:
	PATH="$$HOME/google-cloud-sdk/bin:$$PATH" gcloud builds submit --tag gcr.io/$${PROJECT_ID}/$(IMAGE_NAME)
	PATH="$$HOME/google-cloud-sdk/bin:$$PATH" gcloud run deploy $(IMAGE_NAME) \
		--image gcr.io/$${PROJECT_ID}/$(IMAGE_NAME) \
		--platform managed \
		--region europe-west1 \
		--allow-unauthenticated \
		--port 8080 \
		--cpu 4 \
		--memory 4Gi \
		--min-instances 1 \
		--max-instances 1 \
		--timeout 3600 \
		--no-cpu-throttling \
		--set-env-vars DATABASE_URL=$${DATABASE_URL},CORS_ORIGINS=$${CORS_ORIGINS},ENV=$${ENV},SESSION_SECRET=$${SESSION_SECRET}

# 5173 : default React/Vite port
frontend-dev:
	docker run --rm -p 5173:5173 -v $(shell pwd)/frontend:/app -w /app node:20-alpine sh -c "npm install && npm run dev -- --host"

frontend-build:
	docker run --rm -v $(shell pwd)/frontend:/app -w /app node:20-alpine sh -c "npm install && npm run build"

VIDEO       ?= test.mp4
SERVER_FPS  ?= 14
MAX_FRAMES  ?= 500
test-pipeline:
	docker run --rm --memory=2g -v $(shell pwd):/app -w /app $(IMAGE_NAME) python3 -u test_pipeline.py $(VIDEO) $(SERVER_FPS) $(MAX_FRAMES)

clean:
	docker ps -q --filter ancestor=$(IMAGE_NAME) | xargs -r docker stop || true
	docker ps -aq --filter ancestor=$(IMAGE_NAME) | xargs -r docker rm || true
	docker rmi $(IMAGE_NAME) || true

.PHONY: info test install-docker install-ngrok install-gcloud build run-local tunnel check-gcloud gcloud-auth configure-gcloud deploy-gcloud test-pipeline frontend-dev frontend-build clean