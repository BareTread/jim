import os
import sys
import psutil
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests
from xml.etree import ElementTree
from urllib.parse import urljoin
from pathlib import Path

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# Define the extraction schema for baretread.com
blog_schema = {
    "name": "BareTread Blog Posts",
    "baseSelector": "body",  # Most general container
    "fields": [
        {
            "name": "title",
            "selector": "h1",
            "type": "text",
            "default": ""
        },
        {
            "name": "content",
            "selector": ".entry-content",
            "type": "html",
            "default": ""
        },
        {
            "name": "date",
            "selector": ".posted-on time",
            "type": "text",
            "default": ""
        },
        {
            "name": "categories",
            "selector": ".cat-links a",
            "type": "list",
            "fields": [
                {"name": "category", "type": "text"}
            ]
        },
        {
            "name": "tags",
            "selector": ".tags-links a",
            "type": "list",
            "fields": [
                {"name": "tag", "type": "text"}
            ]
        }
    ]
}

def get_sitemap_urls(base_url: str) -> List[str]:
    """Fetch URLs from sitemap(s)"""
    urls = set()
    
    # Try common sitemap locations
    sitemap_locations = [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/sitemap/sitemap.xml",
        "/wp-sitemap.xml"  # WordPress sitemap
    ]
    
    for sitemap_path in sitemap_locations:
        sitemap_url = urljoin(base_url, sitemap_path)
        try:
            response = requests.get(sitemap_url)
            response.raise_for_status()
            
            root = ElementTree.fromstring(response.content)
            # Handle both sitemap and sitemap index
            namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            # First try to find sitemap locations (in case this is a sitemap index)
            sitemaps = root.findall('.//ns:loc', namespace)
            
            # If this is a sitemap index, fetch each sitemap
            if any(loc.text and loc.text.endswith('.xml') for loc in sitemaps):
                for sitemap in sitemaps:
                    if sitemap.text and sitemap.text.endswith('.xml'):
                        try:
                            sub_response = requests.get(sitemap.text)
                            sub_response.raise_for_status()
                            sub_root = ElementTree.fromstring(sub_response.content)
                            urls.update(loc.text for loc in sub_root.findall('.//ns:loc', namespace))
                        except Exception as e:
                            print(f"Error fetching sub-sitemap {sitemap.text}: {e}")
            else:
                # This is a regular sitemap, just get the URLs
                urls.update(loc.text for loc in sitemaps)
            
            if urls:
                print(f"Found {len(urls)} URLs in {sitemap_url}")
                break
                
        except Exception as e:
            print(f"Error fetching sitemap {sitemap_url}: {e}")
            continue
    
    return list(urls)

def setup_output_directory() -> Path:
    """Create and return output directory with timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("output") / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir

async def save_batch_results(results: List[Dict], output_dir: Path):
    """Save results in an organized structure with separate files for different types of data"""
    results_file = output_dir / "results.jsonl"
    stats_file = output_dir / "stats.json"
    errors_file = output_dir / "errors.jsonl"
    metadata_file = output_dir / "metadata.json"
    
    for result in results:
        # Enhanced content structure for LLM consumption
        content = {
            "url": result["url"],
            "timestamp": datetime.now().isoformat(),
            "content": {
                "title": result.get("title", ""),
                "raw_markdown": result.get("raw_markdown", ""),
                "fit_markdown": result.get("fit_markdown", ""),
                "summary": result.get("summary", ""),
                "references": result.get("references", [])
            },
            "metadata": {
                "date": result.get("date", ""),
                "author": result.get("author", ""),
                "categories": result.get("categories", []),
                "tags": result.get("tags", []),
                "word_count": result.get("word_count", 0),
                "relevance_score": result.get("relevance_score", 0.0)
            },
            "links": result.get("links", {})
        }
        
        with open(results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(content, ensure_ascii=False) + "\n")
        
        if "error" in result:
            with open(errors_file, "a", encoding="utf-8") as f:
                error_entry = {
                    "url": result["url"],
                    "timestamp": datetime.now().isoformat(),
                    "error": result["error"]
                }
                f.write(json.dumps(error_entry, ensure_ascii=False) + "\n")

async def crawl_parallel(urls: List[str], output_dir: Path, max_concurrent: int = 3) -> Dict[str, int]:
    """Crawl URLs in parallel with enhanced content filtering and markdown generation"""
    print(f"\n=== Starting parallel crawl of {len(urls)} URLs ===")
    
    # Configure extraction strategy
    extraction_strategy = JsonCssExtractionStrategy(blog_schema, verbose=True)
    
    # Configure content filters
    pruning_filter = PruningContentFilter(
        threshold=0.45,
        threshold_type="dynamic",
        min_word_threshold=50
    )
    
    # Configure markdown generator
    md_generator = DefaultMarkdownGenerator(
        content_filter=pruning_filter,
        options={
            "citations": True,
            "body_width": 80,
            "escape_html": True
        }
    )
    
    # Minimal browser config for better stability
    browser_config = BrowserConfig(
        headless=True,
        verbose=True,
        extra_args=[
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox"
        ]
    )
    
    # Configure crawler with better wait conditions
    crawl_config = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED,
        extraction_strategy=extraction_strategy,
        markdown_generator=md_generator,
        word_count_threshold=50,
        wait_for="h1",  # Wait for h1 instead of article
        page_timeout=30000,  # Reduced timeout
        wait_for_images=True,  # Handle lazy loading
        remove_overlay_elements=True
    )
    
    # Initialize crawler
    crawler = AsyncWebCrawler(config=browser_config)
    await crawler.start()
    
    stats = {
        "success": 0,
        "failed": 0,
        "timeout": 0,
        "error": 0
    }
    
    try:
        # Process URLs in smaller batches
        for i in range(0, len(urls), max_concurrent):
            batch = urls[i:i + max_concurrent]
            tasks = []
            batch_results = []
            
            for j, url in enumerate(batch):
                session_id = f"session_{i + j}"
                task = crawler.arun(
                    url=url,
                    config=crawl_config,
                    session_id=session_id
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, result in zip(batch, results):
                if isinstance(result, Exception):
                    print(f"Error crawling {url}: {result}")
                    if "timeout" in str(result).lower():
                        stats["timeout"] += 1
                    else:
                        stats["error"] += 1
                    continue
                
                if result.success:
                    try:
                        # Extract content safely
                        content = result.extracted_content
                        if not isinstance(content, dict):
                            content = {}
                        
                        # Get markdown result safely
                        md_result = getattr(result, 'markdown_v2', None)
                        
                        result_dict = {
                            "url": url,
                            "raw_markdown": md_result.raw_markdown if md_result else "",
                            "fit_markdown": md_result.fit_markdown if md_result else "",
                            "title": content.get("title", ""),
                            "date": content.get("date", ""),
                            "categories": content.get("categories", []),
                            "tags": content.get("tags", []),
                            "word_count": len(md_result.raw_markdown.split()) if md_result and md_result.raw_markdown else 0
                        }
                        
                        batch_results.append(result_dict)
                        stats["success"] += 1
                        print(f"Successfully crawled ({stats['success']}/{len(urls)}): {url}")
                    except Exception as e:
                        print(f"Error processing results for {url}: {e}")
                        stats["error"] += 1
                else:
                    print(f"Failed to crawl {url}: {result.error_message}")
                    stats["failed"] += 1
            
            if batch_results:
                await save_batch_results(batch_results, output_dir)
            
            # Small delay between batches
            await asyncio.sleep(1)
    
    finally:
        await crawler.close()
    
    return stats

async def main():
    # Get URLs from sitemap
    base_url = "https://baretread.com"
    urls = get_sitemap_urls(base_url)
    
    if not urls:
        print("No URLs found in sitemap. Exiting...")
        return
    
    print(f"Found {len(urls)} URLs to crawl")
    
    # Create output directory with timestamp
    output_dir = setup_output_directory()
    print(f"Saving results to: {output_dir}")
    
    # Crawl URLs and save results incrementally
    stats = await crawl_parallel(urls, output_dir, max_concurrent=5)
    
    print(f"\nCrawl completed!")
    print(f"Successfully crawled {stats['success']}/{len(urls)} pages")
    print(f"Results saved to: {output_dir}")

if __name__ == "__main__":
    asyncio.run(main()) 