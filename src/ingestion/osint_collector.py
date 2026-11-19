"""
OSINT Collector — reads posts from local/sample sources or a lawfully
provided data feed (e.g., an analyst-uploaded export, a partner threat-intel
feed). This is the recommended entry point for demos and for any real
deployment where data has already been lawfully obtained.
"""

import json
from pathlib import Path
from typing import List, Dict

from src.utils.logger import get_logger, audit_log

logger = get_logger()


def load_posts_from_json(file_path: str, actor: str = "system") -> List[Dict]:
    """
    Load a list of posts from a local JSON file.

    Expected format:
    [
      {"alias": "shadowbroker99", "text": "...", "source": "forum_x", "timestamp": "..."},
      ...
    ]
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No such file: {file_path}")

    with open(path, "r") as f:
        posts = json.load(f)

    logger.info(f"Loaded {len(posts)} posts from {file_path}")
    audit_log(
        action="ingest",
        actor=actor,
        details={"source": str(file_path), "count": len(posts)},
    )
    return posts


def load_posts_from_feed(feed_url: str, api_key: str, actor: str = "system") -> List[Dict]:
    """
    Placeholder for a lawful partner threat-intel feed integration
    (e.g., an internal law-enforcement data-sharing API). Implement the
    actual request logic against your organization's authorized feed.
    """
    raise NotImplementedError(
        "Wire this up to your organization's authorized threat-intel feed. "
        "Do not implement unauthorized scraping here — see docs/ETHICS_AND_LEGAL.md."
    )
