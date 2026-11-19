"""
Forum Scraper (template) — structure for collecting posts from a specific,
pre-authorized forum/marketplace target through the Tor network.

IMPORTANT:
- This is a STRUCTURAL TEMPLATE, not a ready-to-run scraper against any
  specific site. You must supply your own authorized `target_url` and
  confirm legal authorization before use — see docs/ETHICS_AND_LEGAL.md.
- Routes traffic through the standard Tor SOCKS proxy (same mechanism any
  Tor Browser user relies on) — this does not break or attack Tor in any
  way, it simply lets a legally authorized collector reach a .onion address.
- Includes rate limiting to avoid disrupting the target site and to reduce
  detection risk to field investigators.
"""

import time
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

from src.utils.config import load_config
from src.utils.logger import get_logger, audit_log

logger = get_logger()


class ForumScraper:
    def __init__(self, target_url: str, actor: str = "system"):
        """
        Args:
            target_url: the specific, pre-authorized forum/thread URL to
                collect from. Must be supplied by the analyst per-case —
                intentionally NOT hardcoded in this template.
            actor: identifier of the analyst/system running this collector,
                used for the audit log.
        """
        cfg = load_config()
        self.target_url = target_url
        self.actor = actor
        self.rate_limit_seconds = cfg["ingestion"]["rate_limit_seconds_between_requests"]
        self.session = requests.Session()
        self.session.proxies = {
            "http": cfg["ingestion"]["tor_proxy"],
            "https": cfg["ingestion"]["tor_proxy"],
        }

    def fetch_page(self, url: str) -> Optional[str]:
        """Fetch a single page's HTML, respecting the configured rate limit."""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            time.sleep(self.rate_limit_seconds)
            return resp.text
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def parse_posts(self, html: str) -> List[Dict]:
        """
        Parse posts out of a page's HTML. The CSS selectors below are
        placeholders — you MUST adapt them to the specific, authorized
        target's actual markup structure.
        """
        soup = BeautifulSoup(html, "lxml")
        posts = []
        for post_el in soup.select(".post"):  # placeholder selector
            alias_el = post_el.select_one(".post-author")
            text_el = post_el.select_one(".post-body")
            ts_el = post_el.select_one(".post-timestamp")
            if not (alias_el and text_el):
                continue
            posts.append({
                "alias": alias_el.get_text(strip=True),
                "text": text_el.get_text(strip=True),
                "timestamp": ts_el.get_text(strip=True) if ts_el else None,
                "source": self.target_url,
            })
        return posts

    def run(self) -> List[Dict]:
        html = self.fetch_page(self.target_url)
        if html is None:
            return []
        posts = self.parse_posts(html)
        logger.info(f"Collected {len(posts)} posts from {self.target_url}")
        audit_log(
            action="ingest",
            actor=self.actor,
            details={"source": self.target_url, "count": len(posts)},
        )
        return posts


if __name__ == "__main__":
    print(
        "This is a structural template. Supply an authorized target_url and "
        "confirm legal authorization before running against a real target."
    )
