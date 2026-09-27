#!/bin/bash
set -e

echo "🚀 Starting DocParser development environment..."

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found. Please install Docker Desktop."
    exit 1
fi

# Start services
echo "📦 Starting PostgreSQL, Redis, MinIO..."
docker-compose -f docker/docker-compose.yml up -d postgres redis minio

# Wait for services to be healthy
echo "⏳ Waiting for services to be ready..."
sleep 5

# Run migrations
echo "🔄 Running database migrations..."
docker-compose -f docker/docker-compose.yml run --rm api alembic upgrade head

# Start API and worker
echo "🌐 Starting API and Worker..."
docker-compose -f docker/docker-compose.yml up -d api worker flower

echo "✅ Development environment ready!"
echo ""
echo "📍 Services:"
echo "   API:       http://localhost:8000"
echo "   Docs:      http://localhost:8000/docs"
echo "   Flower:    http://localhost:5555"
echo "   MinIO:     http://localhost:9001 (minioadmin/minioadmin)"
echo "   PostgreSQL: localhost:5432 (docparser/docparser)"
echo "   Redis:     localhost:6379"
echo ""
echo "📝 To view logs: docker-compose -f docker/docker-compose.yml logs -f"
echo "🛑 To stop:      docker-compose -f docker/docker-compose.yml down"