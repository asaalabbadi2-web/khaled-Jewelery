# Multi-stage build: Flutter Web -> Nginx
# Produces a self-contained image that serves Flutter Web and proxies /api to backend.

# 1) Build Flutter web
FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app

# Copy pubspec first for better caching
COPY frontend/pubspec.yaml frontend/pubspec.lock* /app/
RUN flutter pub get

# Copy the rest of the frontend
COPY frontend /app

# Compile-time API base URL for the web app (ApiService reads dart-define API_BASE_URL)
ARG API_BASE_URL=/api

RUN flutter build web --release --no-tree-shake-icons --dart-define=API_BASE_URL=${API_BASE_URL}

# 2) Serve with nginx
FROM nginx:1.27-alpine

COPY ops/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build/web /usr/share/nginx/html

EXPOSE 80
