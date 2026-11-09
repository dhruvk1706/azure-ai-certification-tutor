# Build context is the repository root (see infrastructure/docker-compose.yml).
FROM node:24-slim
WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/
RUN npm ci
COPY frontend frontend
CMD ["npm", "run", "dev", "-w", "frontend", "--", "--host", "0.0.0.0"]
