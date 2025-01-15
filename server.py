import os
from dotenv import load_dotenv
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Print environment variables for debugging
logger.info("Environment variables:")
logger.info(f"PORT from env: {os.getenv('PORT')}")
logger.info(f"CRAWL4AI_DB_PATH: {os.getenv('CRAWL4AI_DB_PATH')}")

# Set database path before importing crawl4ai
os.environ['CRAWL4AI_DB_PATH'] = os.getenv('CRAWL4AI_DB_PATH', '/app/data')
os.environ['HOME'] = os.getenv('HOME', '/app')

# Ensure DB directory exists with proper permissions
db_path = os.environ['CRAWL4AI_DB_PATH']
os.makedirs(db_path, exist_ok=True)

from fastapi import FastAPI, HTTPException, Depends, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai.content_filter_strategy import PruningContentFilter, BM25ContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from pydantic import BaseModel, Field
import uvicorn
import asyncio
import uuid
from typing import Dict, Any, Union, List, Optional
from contextlib import asynccontextmanager

# Configuration
API_TOKEN = os.getenv("CRAWL4AI_API_TOKEN")
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "5"))
PORT = int(os.getenv("PORT", "11235"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_PATH = os.getenv("CRAWL4AI_DB_PATH", "/app/data")

# Security
security = HTTPBearer()

# Get Chrome flags from environment
CHROME_FLAGS = os.getenv('CHROME_FLAGS', '--disable-gpu --no-sandbox').split()

class CrawlRequest(BaseModel):
    urls: Union[str, List[str]]
    priority: int = Field(default=1, ge=1, le=10)
    use_llm: bool = Field(default=False, description="Use LLM for enhanced extraction")
    custom_schema: Optional[dict] = Field(default=None, description="Custom extraction schema")
    search_query: Optional[str] = Field(default=None, description="Search query for BM25 content filtering")
    extract_json: bool = Field(default=True, description="Extract structured JSON data")
    content_filter: str = Field(default="pruning", description="Content filter type: pruning, bm25, or none")
    filter_threshold: float = Field(default=0.5, description="Threshold for content filtering")
    wait_for: str = Field(default="domcontentloaded", description="Wait condition: domcontentloaded, load, networkidle0, networkidle2")
    page_timeout: int = Field(default=30000, ge=1000, le=60000, description="Page load timeout in milliseconds (1-60s)")

# Global state
crawler = None
tasks: Dict[str, Any] = {}
task_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> bool:
    """Verify API token if configured"""
    if not API_TOKEN:
        return True
    return credentials.credentials == API_TOKEN

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global crawler
    logger.info("Starting server initialization...")
    logger.info(f"Using database path: {DB_PATH}")
    logger.info(f"Chrome flags: {CHROME_FLAGS}")
    
    browser_config = BrowserConfig(
        headless=True,
        verbose=True,
        extra_args=CHROME_FLAGS,
        viewport_width=1920,
        viewport_height=1080
    )
    
    try:
        logger.info("Initializing crawler...")
        crawler = AsyncWebCrawler(
            config=browser_config
        )
        logger.info("Crawler initialized successfully")
        
        async with crawler:
            logger.info("Server ready to accept requests")
            yield
    except Exception as e:
        logger.error(f"Error during initialization: {str(e)}")
        raise
    finally:
        logger.info("Shutting down server...")
        crawler = None

app = FastAPI(
    title="Crawl4AI API",
    description="Advanced web crawling and content extraction API",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "max_concurrent_tasks": MAX_CONCURRENT_TASKS,
        "active_tasks": len(tasks),
        "llm_enabled": False  # LLM support disabled for now
    }

@app.post("/crawl")
async def crawl(
    request: CrawlRequest,
    token: bool = Depends(verify_token)
):
    """Submit a new crawl job"""
    if request.use_llm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM support is currently disabled"
        )
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"status": "pending", "result": None}
    
    # Start crawling in background
    asyncio.create_task(process_crawl(task_id, request))
    
    return {"task_id": task_id}

@app.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    token: bool = Depends(verify_token)
):
    """Get status of a crawl task"""
    if task_id not in tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    return tasks[task_id]

async def process_crawl(task_id: str, request: CrawlRequest):
    """Process a crawl request with advanced extraction"""
    async with task_semaphore:
        try:
            url = request.urls if isinstance(request.urls, str) else request.urls[0]
            
            # Cap timeout and handle wait conditions
            page_timeout = min(request.page_timeout, 30000)  # Max 30 seconds
            wait_condition = request.wait_for
            if wait_condition == "networkidle0":
                wait_condition = "domcontentloaded"  # More reliable default
            
            # Setup content filter
            content_filter = None
            if request.content_filter == "pruning":
                content_filter = PruningContentFilter(
                    threshold=request.filter_threshold,
                    threshold_type="dynamic",
                    min_word_threshold=50
                )
            elif request.content_filter == "bm25" and request.search_query:
                content_filter = BM25ContentFilter(
                    user_query=request.search_query,
                    bm25_threshold=request.filter_threshold
                )
            
            # Setup markdown generator with content filter
            md_generator = DefaultMarkdownGenerator(
                content_filter=content_filter
            )
            
            # Setup JSON extraction if requested
            extraction_strategy = None
            if request.extract_json and request.custom_schema:
                extraction_strategy = JsonCssExtractionStrategy(
                    schema=request.custom_schema,
                    verbose=True
                )
            
            # Configure crawler with optimized settings
            config = CrawlerRunConfig(
                cache_mode=CacheMode.ENABLED,
                markdown_generator=md_generator,
                extraction_strategy=extraction_strategy,
                word_count_threshold=50,
                wait_until=wait_condition,
                page_timeout=page_timeout,
                wait_for_images=True
            )
            
            # Configure browser with optimized settings
            browser_config = BrowserConfig(
                headless=True,
                verbose=True,
                extra_args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage"
                ],
                viewport_width=1920,
                viewport_height=1080
            )
            
            logger.info(f"Starting crawl for {url} with wait condition: {wait_condition}, timeout: {page_timeout}ms")
            
            result = await crawler.arun(
                url=url,
                config=config,
                browser_config=browser_config
            )
            
            if result.success:
                tasks[task_id] = {
                    "status": "completed",
                    "result": {
                        "url": url,
                        "raw_markdown": result.markdown_v2.raw_markdown if hasattr(result, 'markdown_v2') else None,
                        "fit_markdown": result.markdown_v2.fit_markdown if hasattr(result, 'markdown_v2') else None,
                        "extracted_json": result.extracted_content if request.extract_json else None,
                        "links": result.links if hasattr(result, 'links') else [],
                        "images": result.images if hasattr(result, 'images') else [],
                        "stats": {
                            "crawl_time_ms": int((time.time() - result.start_time) * 1000) if hasattr(result, 'start_time') else None,
                            "page_size_bytes": len(result.raw_html) if hasattr(result, 'raw_html') else None
                        }
                    }
                }
                logger.info(f"Successfully crawled {url}")
            else:
                error_msg = result.error_message if hasattr(result, 'error_message') else str(result)
                logger.error(f"Failed to crawl {url}: {error_msg}")
                tasks[task_id] = {
                    "status": "failed",
                    "error": error_msg
                }
                
        except Exception as e:
            logger.error(f"Error processing crawl request: {str(e)}")
            tasks[task_id] = {
                "status": "failed",
                "error": str(e)
            }

if __name__ == "__main__":
    logger.info(f"Starting server on port {PORT}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level="info"
    ) 