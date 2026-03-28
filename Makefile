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
	@echo ""
	@echo "🧪 LOCAL TESTING :"
	@echo "   make test              # Build + run app → http://localhost:$(HTTP_PORT)"
	@echo ""
	@echo "📱 LOCAL TESTING WITH PHONE :"
	@echo "   1. make test           # Terminal 1 — start container"
	@echo "   2. make tunnel         # Terminal 2 — expose to phone"
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

install-ngrok:
	curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
	| sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
	&& echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
	| sudo tee /etc/apt/sources.list.d/ngrok.list \
	&& sudo apt update \
	&& sudo apt install ngrok
	@echo "Run: ngrok config add-authtoken <token>"

build:
	docker build -t $(IMAGE_NAME) .

run-local:
	docker run -p $(HTTP_PORT):8080 --memory=2g --env-file .env $(IMAGE_NAME)

tunnel:
	ngrok http $(HTTP_PORT)

gcloud-auth:
	gcloud auth login
	gcloud config set project $${PROJECT_ID}

configure-gcloud:
	gcloud run services update $(IMAGE_NAME) \
		--region europe-west1 \
		--cpu 2 \
		--max-instances 1

deploy-gcloud:
	gcloud builds submit --tag gcr.io/$${PROJECT_ID}/$(IMAGE_NAME)
	gcloud run deploy $(IMAGE_NAME) \
		--image gcr.io/$${PROJECT_ID}/$(IMAGE_NAME) \
		--platform managed \
		--region europe-west1 \
		--allow-unauthenticated \
		--port 8080 \
		--set-env-vars DATABASE_URL=$${DATABASE_URL}

clean:
	docker ps -q --filter ancestor=$(IMAGE_NAME) | xargs -r docker stop || true
	docker ps -aq --filter ancestor=$(IMAGE_NAME) | xargs -r docker rm || true
	docker rmi $(IMAGE_NAME) || true

.PHONY: info test install-docker install-ngrok build run-local tunnel gcloud-auth deploy-gcloud clean configure-gcloud