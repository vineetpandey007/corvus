"""
End-to-end demo pipeline runner.

Usage:
    python scripts/run_pipeline.py --input data/sample/sample_posts.json

Loads posts, runs stylometry + PGP + wallet correlation across all pairs,
builds the identity graph, and writes both a JSON export and a PNG render
to data/processed/.
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion.osint_collector import load_posts_from_json
from src.identity_graph.graph_builder import IdentityGraphBuilder
from src.visualization.graph_viz import render_static_png, export_json
from src.utils.logger import get_logger

logger = get_logger()


def main():
    parser = argparse.ArgumentParser(description="Run the de-anonymization demo pipeline.")
    parser.add_argument("--input", required=True, help="Path to a posts JSON file")
    parser.add_argument("--actor", default="demo_analyst", help="Analyst identifier for audit log")
    parser.add_argument("--case-id", default="demo-case-01", help="Case identifier to scope the graph under")
    args = parser.parse_args()

    posts = load_posts_from_json(args.input, actor=args.actor)

    builder = IdentityGraphBuilder(case_id=args.case_id)
    builder.build_from_posts(posts, actor=args.actor)
    graph = builder.get_networkx_graph()

    json_path = export_json(graph, "data/processed/demo_graph.json")
    png_path = render_static_png(graph, "data/processed/demo_graph.png")

    print("\n=== Identity Graph Summary ===")
    print(f"Aliases analyzed: {len(graph.nodes)}")
    print(f"Correlations found: {len(graph.edges)}")
    for u, v, attrs in graph.edges(data=True):
        print(f"  {u}  <-->  {v}   types={attrs['types']}   confidence={attrs['confidence']:.2f}")

    print(f"\nJSON graph saved to: {json_path}")
    print(f"PNG graph saved to:  {png_path}")


if __name__ == "__main__":
    main()
