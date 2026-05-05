### Real-time Foosball Analytics System

Try it here :

[![Live](https://img.shields.io/badge/live-kickanalytics.live-blue?style=flat-square)](https://kickanalytics.live)

Built a custom dataset and annotation pipeline (Roboflow) and trained a YOLOv8 model, optimized with ONNX Runtime
(INT8 quantization, -75% model size).
Designed a full-stack system (Python async backend, React frontend, PostgreSQL) with real-time WebSocket streaming
(<100ms latency).
Implemented homography-based tracking and live analytics (goals, possession, ball speed).
Deployed on Google Cloud Run with Docker, enabling scalable, production-ready infrastructure with a user-first design
