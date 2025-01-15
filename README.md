# Crawl4AI Web Scraping Tool

A powerful web scraping tool built with Crawl4AI for extracting structured content from websites. Optimized for knowledge extraction and LLM processing.

## Features

- FastAPI-based REST API server
- Parallel web crawling with configurable concurrency
- Structured content extraction with customizable schemas
- Markdown generation with citations
- Docker support for easy deployment
- Sitemap-based URL discovery

## Prerequisites

- Python 3.9+
- Docker (optional)
- Chrome/Chromium browser

## Setup

1. Clone the repository:
```bash
git clone <your-repo-url>
cd crawl4ai
```

2. Create and configure environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys
```

3. Install dependencies:
```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Running Locally

1. Start the API server:
```bash
python server.py
```

2. Crawl a website:
```bash
python crawl_site.py --url https://example.com
```

3. Run tests:
```bash
python test_docker.py
```

### Using Docker

1. Build and run with docker-compose:
```bash
docker-compose up --build
```

2. Or build and run manually:
```bash
docker build -t crawl4ai .
docker run -p 11235:11235 --env-file .env crawl4ai
```

## API Endpoints

- `GET /health` - Health check
- `POST /crawl` - Submit crawl job
- `GET /task/{task_id}` - Get task status

### Example Request

```bash
curl -X POST http://localhost:11235/crawl \
  -H "Content-Type: application/json" \
  -d '{"urls": "https://example.com", "priority": 1}'
```

## Configuration

Key environment variables:

- `CRAWL4AI_API_TOKEN` - API security token
- `OPENAI_API_KEY` - OpenAI API key
- `ANTHROPIC_API_KEY` - Anthropic API key
- `MAX_CONCURRENT_TASKS` - Maximum concurrent crawl tasks

## Output

Results are saved in the `output` directory with timestamped folders containing:
- `results.jsonl` - Extracted content
- `stats.json` - Crawl statistics
- `errors.jsonl` - Error logs
- `metadata.json` - Crawl metadata

## License

MIT License
