import requests
import json
import time
import os
import psutil
from typing import Optional, List, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Crawl4AiTester:
    def __init__(self, base_url: str = "https://jim-production.up.railway.app", api_token: str = "jeremy"):
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self.process = psutil.Process(os.getpid())
        self.peak_memory = 0

    def log_memory(self, prefix: str = "") -> None:
        """Log current and peak memory usage"""
        current_mem = self.process.memory_info().rss
        if current_mem > self.peak_memory:
            self.peak_memory = current_mem
        print(f"{prefix} Memory Usage: {current_mem // (1024 * 1024)}MB, Peak: {self.peak_memory // (1024 * 1024)}MB")

    def submit_and_wait(self, request_data: dict, timeout: int = 300) -> dict:
        # Submit crawl job
        print(f"\nSubmitting crawl request for: {request_data.get('urls')}")
        print(f"Request configuration: {json.dumps(request_data, indent=2)}")
        
        self.log_memory("Before crawl: ")
        
        response = requests.post(
            f"{self.base_url}/crawl",
            headers=self.headers,
            json=request_data
        )
        response.raise_for_status()
        
        # Get task ID from response
        task_data = response.json()
        if not task_data or "task_id" not in task_data:
            raise Exception("No task ID received from server")
            
        task_id = task_data["task_id"]
        print(f"Task ID: {task_id}")

        # Poll for result with progress tracking
        print("\nChecking task status...")
        start_time = time.time()
        last_status = None
        dots = 0
        
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Task {task_id} timeout after {timeout} seconds")

            result = requests.get(
                f"{self.base_url}/task/{task_id}",
                headers=self.headers
            )
            
            try:
                status = result.json()
                current_status = status.get("status")
                
                # Only print status if it changed
                if current_status != last_status:
                    print(f"\nStatus: {current_status}")
                    last_status = current_status
                    self.log_memory(f"Status {current_status}: ")
                
                # Print progress indicator
                dots = (dots + 1) % 4
                print("." * dots + " " * (3 - dots) + "\r", end="", flush=True)
                
                if status.get("error"):
                    print(f"\nError details: {status['error']}")
                
                if current_status == "completed":
                    print("\nTask completed!")
                    self.log_memory("After completion: ")
                    return status
                elif current_status == "failed":
                    print(f"\nFull error response: {json.dumps(status, indent=2)}")
                    self.log_memory("After failure: ")
                    raise Exception(f"Task failed: {status.get('error', 'Unknown error')}")
                
            except json.JSONDecodeError:
                print(".", end="", flush=True)
            
            time.sleep(2)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Submit a URL for crawling")
    parser.add_argument("url", help="URL to crawl")
    parser.add_argument("--output", help="Output file path (optional)")
    parser.add_argument("--timeout", type=int, default=120000, help="Page timeout in ms (default: 120000)")
    parser.add_argument("--api-url", default="https://jim-production.up.railway.app", help="API endpoint")
    parser.add_argument("--token", default="jeremy", help="API token")
    parser.add_argument("--wait-for", default="load", 
                       choices=["load", "domcontentloaded", "networkidle0", "networkidle2"],
                       help="Wait condition (default: load)")
    
    args = parser.parse_args()
    
    try:
        tester = Crawl4AiTester(args.api_url, args.token)
        
        # Configure request with optimized settings
        request = {
            "urls": args.url,
            "priority": 1,
            "use_llm": False,
            "content_filter": "pruning",
            "filter_threshold": 0.5,
            "wait_for": args.wait_for,
            "page_timeout": min(args.timeout, 30000),  # Cap at 30 seconds as per server
            "extract_json": False,
            "custom_schema": None,
            "search_query": None,
            "wait_for_images": True  # From v0.4.1 documentation
        }
        
        print("\nAttempting to crawl with optimized configuration...")
        print(f"Using API endpoint: {args.api_url}")
        print(f"Wait condition: {args.wait_for}")
        print(f"Timeout: {min(args.timeout, 30000)}ms")
        
        results = tester.submit_and_wait(request)
        
        # Process results if successful
        if results:
            # Save results
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                print(f"\nResults saved to: {args.output}")
            
            print("\nCrawl completed successfully!")
            
            # Print stats
            if "result" in results:
                result = results["result"]
                print(f"\nStats:")
                if isinstance(result, dict):
                    # Print basic info
                    print(f"URL: {result.get('url', 'N/A')}")
                    
                    # Handle markdown content
                    raw_markdown = result.get('raw_markdown')
                    fit_markdown = result.get('fit_markdown')
                    if raw_markdown:
                        print(f"\nRaw markdown length: {len(raw_markdown)}")
                        print("\nFirst 500 characters of raw markdown:")
                        print(raw_markdown[:500] + "...")
                    if fit_markdown:
                        print(f"\nFit markdown length: {len(fit_markdown)}")
                    
                    # Handle links and images
                    links = result.get('links', [])
                    images = result.get('images', [])
                    if links:
                        print(f"\nLinks found: {len(links)}")
                        if len(links) > 0:
                            print("\nFirst 5 links:")
                            for link in links[:5]:
                                print(f"- {link}")
                    if images:
                        print(f"\nImages found: {len(images)}")
                        if len(images) > 0:
                            print("\nFirst 5 images:")
                            for img in images[:5]:
                                print(f"- {img}")
                    
                    # Print crawl stats if available
                    stats = result.get('stats', {})
                    if stats:
                        print("\nCrawl stats:")
                        print(f"Crawl time: {stats.get('crawl_time_ms', 'N/A')}ms")
                        print(f"Page size: {stats.get('page_size_bytes', 'N/A')} bytes")
                else:
                    print("Result format not recognized")
                    print(f"Raw result: {json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"\nError: {str(e)}")
        if hasattr(e, 'response') and hasattr(e.response, 'json'):
            try:
                error_details = e.response.json()
                print(f"Error details: {json.dumps(error_details, indent=2)}")
            except:
                pass
        exit(1)

if __name__ == "__main__":
    main() 