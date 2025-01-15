import asyncio
import json
import requests
import time
import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DEFAULT_URL = "https://jim-production.up.railway.app"
API_URL = os.getenv("CRAWL4AI_API_URL", DEFAULT_URL)
API_TOKEN = os.getenv("CRAWL4AI_API_TOKEN", "jeremy")

def test_crawl(url: str = "https://baretread.com/products/", api_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Test the crawling functionality of the service
    
    Args:
        url: The URL to crawl
        api_url: Optional API URL override
    
    Returns:
        Dict containing the crawl results or None if failed
    """
    api_url = api_url or API_URL
    print(f"\nTesting crawl for: {url}")
    print(f"Using API endpoint: {api_url}")
    
    # Always include Authorization header with the token
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        # Test health check
        health_response = requests.get(f"{api_url}/health", headers=headers)
        health_response.raise_for_status()
        print("Health check passed!")
        
        # Submit crawl job
        crawl_url = f"{api_url}/crawl"
        payload = {
            "urls": url,
            "priority": 1
        }
        
        print("\nSubmitting payload:", json.dumps(payload, indent=2))
        response = requests.post(crawl_url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        print("\nCrawl job submitted:", json.dumps(result, indent=2))
        
        # Poll for results
        task_id = result.get("task_id")
        if not task_id:
            print("No task ID received")
            return None
            
        max_retries = 30
        retry_delay = 2
        
        for i in range(max_retries):
            task_response = requests.get(f"{api_url}/task/{task_id}", headers=headers)
            task_response.raise_for_status()
            task_result = task_response.json()
            
            if task_result["status"] == "completed":
                print("\nCrawl completed successfully!")
                return task_result["result"]
            elif task_result["status"] == "failed":
                print(f"\nCrawl failed: {task_result.get('error')}")
                return None
            elif task_result["status"] == "pending":
                print(f"Task pending... (attempt {i+1}/{max_retries})")
                time.sleep(retry_delay)
                continue
                
        print("\nTimeout waiting for results")
        return None
            
    except Exception as e:
        print(f"Error: {str(e)}")
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            print(f"Response details: {e.response.text}")
        return None

def save_results(results: Dict[str, Any], output_file: str):
    """Save crawl results to a file"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_file}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test the Crawl4AI service')
    parser.add_argument('--url', default="https://baretread.com/products/",
                      help='URL to crawl')
    parser.add_argument('--api-url', default=None,
                      help='API endpoint URL')
    parser.add_argument('--output', default=None,
                      help='Output file for results')
    
    args = parser.parse_args()
    
    result = test_crawl(url=args.url, api_url=args.api_url)
    
    if result:
        print("\nExample of extracted content:")
        print(json.dumps(result, indent=2)[:500] + "...")
        
        if args.output:
            save_results(result, args.output) 