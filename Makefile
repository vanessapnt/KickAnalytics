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
	@echo "💻 LOCAL DEV (recommended — no Docker, hot reload) :"
	@echo "   Terminal 1 : make dev-server     # Python server on :$(HTTP_PORT) (.env loaded automatically)"
	@echo "   Terminal 2 : make dev-frontend   # Vite dev server on :5173 (hot reload)"
	@echo "   Open       : http://localhost:5173"
	@echo ""
	@echo "   If you prefer running manually :"
	@echo "   Terminal 1 : export \$$(grep -v '^#' .env | xargs) && ENV=development python3 back/server.py"
	@echo "   Terminal 2 : cd frontend && npm run dev"
	@echo ""
	@echo "🧪 LOCAL TESTING (full Docker stack) :"
	@echo "   make test              # Build frontend + Docker image + run -> http://localhost:$(HTTP_PORT)"
	@echo ""
	@echo "📱 LOCAL TESTING WITH PHONE :"
	@echo "   1. make test           # Terminal 1 — start container"
	@echo ""
	@echo "⚛️  REACT FRONTEND :"
	@echo "   make frontend-build    # Build React -> frontend/dist/ (done automatically by make test)"
	@echo ""
	@echo "☁️  GOOGLE CLOUD DEPLOYMENT :"
	@echo "   1. Configure .env with PROJECT_ID"
	@echo "   2. make install-gcloud # Install Google Cloud SDK"
	@echo "   3. make gcloud-auth    # Authenticate Google Cloud (once)"
	@echo "   4. make deploy-gcloud  # Build frontend + deploy -> Google displays final URL"
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

install-gcloud:
	curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts
	@echo "Run: source ~/.bashrc"

build: frontend-build
	docker build -t $(IMAGE_NAME) .

run-local:
	docker run -p $(HTTP_PORT):8080 --memory=2g --env-file .env -e ENV=$${ENV} $(IMAGE_NAME)

install-clouflared:
	curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/cloudflared
	chmod +x ~/cloudflared

tunnel:
	@test -f ~/cloudflared || $(MAKE) install-clouflared
	~/cloudflared tunnel --url http://127.0.0.1:$(HTTP_PORT)

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

deploy-gcloud: frontend-build
	PATH="$$HOME/google-cloud-sdk/bin:$$PATH" gcloud builds submit --tag gcr.io/$${PROJECT_ID}/$(IMAGE_NAME)
	@printf 'DATABASE_URL: "%s"\nCORS_ORIGINS: "%s"\nENV: "%s"\nSESSION_SECRET: "%s"\nADMIN_USERNAMES: "%s"\n' \
		"$${DATABASE_URL}" "$${CORS_ORIGINS}" "$${ENV}" "$${SESSION_SECRET}" "$${ADMIN_USERNAMES}" > /tmp/ka-env-vars.yaml
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
		--env-vars-file /tmp/ka-env-vars.yaml
	@rm -f /tmp/ka-env-vars.yaml

dev-server:
	ENV=development python3 back/server.py

dev-frontend:
	cd frontend && npm run dev

# 5173 : default React/Vite port
frontend-dev:
	docker run --rm -p 5173:5173 -v $(shell pwd)/frontend:/app -w /app node:20-alpine sh -c "npm install && npm run dev -- --host"

frontend-build:
	docker run --rm -v $(shell pwd)/frontend:/app -w /app node:20-alpine sh -c "npm install && npm run build"

SERVER      ?= https://todo.run.app
CAM_USER    ?= admin
CAM_PASS    ?= password
VIDEO       ?= frontend/public/test2.mp4
SERVER_FPS  ?= 14
MAX_FRAMES  ?= 500
test-pipeline:
	docker run --rm --memory=2g -v $(shell pwd):/app -w /app $(IMAGE_NAME) python3 -u back/test_pipeline.py $(VIDEO) $(SERVER_FPS) $(MAX_FRAMES)

test-pipeline-dev:
	cd back && python3 -u test_pipeline.py ../$(VIDEO) $(SERVER_FPS) $(MAX_FRAMES)

send-video:
	python3 colab_camera_sender.py --server $(SERVER) --video $(VIDEO) --user $(CAM_USER) --password $(CAM_PASS) --fps $(SERVER_FPS) --loop

send-video-local:
	python3 colab_camera_sender.py --server http://localhost:$(HTTP_PORT) --video $(VIDEO) --user $(CAM_USER) --password $(CAM_PASS) --fps $(SERVER_FPS) --loop

clean:
	docker ps -q --filter ancestor=$(IMAGE_NAME) | xargs -r docker stop || true
	docker ps -aq --filter ancestor=$(IMAGE_NAME) | xargs -r docker rm || true
	docker rmi $(IMAGE_NAME) || true

.PHONY: info test install-docker install-gcloud build install-clouflared run-local tunnel check-gcloud gcloud-auth configure-gcloud deploy-gcloud test-pipeline test-pipeline-dev send-video send-video-local dev-server dev-frontend frontend-dev frontend-build clean