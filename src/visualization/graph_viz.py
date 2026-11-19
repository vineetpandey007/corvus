"""
Visualization helpers — render the identity graph either as a static PNG
(for reports) or export JSON in a shape ready for a frontend graph library
(Cytoscape.js / D3.js / react-force-graph).
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx


def render_static_png(graph: nx.Graph, output_path: str = "data/processed/identity_graph.png"):
    """Render the graph to a PNG for inclusion in a report/pitch deck."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(11, 8))
    # k spaces nodes apart proportional to graph size so labels don't
    # overlap/clip on small graphs, and isolated (no-edge) nodes don't get
    # pushed to a far corner away from the rest of the layout.
    k = 1.6 / max(len(graph.nodes) ** 0.5, 1)
    pos = nx.spring_layout(graph, seed=42, k=k)

    nx.draw_networkx_nodes(graph, pos, node_size=1800, node_color="#1f77b4")
    nx.draw_networkx_labels(graph, pos, font_size=8, font_color="white")

    edge_weights = [graph[u][v].get("confidence", 0.5) * 3 for u, v in graph.edges]
    nx.draw_networkx_edges(graph, pos, width=edge_weights, alpha=0.6)

    edge_labels = {
        (u, v): ",".join(graph[u][v].get("types", [])) for u, v in graph.edges
    }
    nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=7)

    plt.title("Identity Correlation Graph")
    plt.axis("off")
    plt.margins(0.15)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()

    return output_path


def export_json(graph: nx.Graph, output_path: str = "data/processed/identity_graph.json"):
    """Export graph as {nodes, edges} JSON for the React/Cytoscape frontend."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    data = {
        "nodes": [{"id": n, **graph.nodes[n]} for n in graph.nodes],
        "edges": [{"source": u, "target": v, **graph[u][v]} for u, v in graph.edges],
    }
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    return output_path
