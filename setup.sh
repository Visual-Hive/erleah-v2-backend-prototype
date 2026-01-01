#!/bin/bash
# Quick start script for Erleah backend development

set -e

echo "🚀 Setting up Erleah Backend..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your ANTHROPIC_API_KEY"
    echo "   Then run this script again."
    exit 1
fi

# Check if ANTHROPIC_API_KEY is set
if grep -q "your-key-here" .env; then
    echo "⚠️  Please add your ANTHROPIC_API_KEY to .env file"
    exit 1
fi

# Start databases
echo "🐳 Starting databases (PostgreSQL, Qdrant, Redis)..."
docker-compose up -d

# Wait for databases to be ready
echo "⏳ Waiting for databases to be ready..."
sleep 5

# Install dependencies
echo "📦 Installing Python dependencies..."
if command -v uv &> /dev/null; then
    uv sync
else
    pip install -e .
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the server:"
echo "  uvicorn src.main:app --reload"
echo ""
echo "Or:"
echo "  python -m src.main"
echo ""
echo "API will be available at:"
echo "  http://localhost:8000"
echo "  http://localhost:8000/docs (Swagger UI)"
echo ""
