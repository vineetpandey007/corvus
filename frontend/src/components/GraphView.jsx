import { useMemo, useRef } from "react";
import CytoscapeComponent from "react-cytoscapejs";

const TYPE_COLORS = {
  stylometry: "#4C6EF5",
  pgp_key_reuse: "#F03E3E",
  wallet_reuse: "#F59F00",
  username_similarity: "#12B886",
};

/**
 * Renders the identity correlation graph. Edge color reflects the
 * strongest/first correlation type; edge width reflects confidence.
 * Nodes are aliases; hovering/clicking is left to Cytoscape defaults
 * (zoom/pan/drag work out of the box).
 */
export default function GraphView({ graph }) {
  // Holds the underlying Cytoscape core instance once mounted (via the
  // `cy` callback prop below) so the export buttons can call its built-in
  // cy.png()/cy.jpg() — this exports exactly what's on screen right now
  // (current pan/zoom/layout), which is more useful than a fresh
  // server-side render that wouldn't reflect the analyst's current view.
  const cyRef = useRef(null);

  const elements = useMemo(() => {
    if (!graph) return [];
    const nodeEls = graph.nodes.map((n) => ({
      data: { id: n.id, label: n.id },
    }));
    const edgeEls = graph.edges.map((e, idx) => ({
      data: {
        id: `edge-${idx}`,
        source: e.source,
        target: e.target,
        label: (e.types || []).join(", "),
        confidence: e.confidence,
        color: TYPE_COLORS[(e.types || [])[0]] || "#868E96",
      },
    }));
    return [...nodeEls, ...edgeEls];
  }, [graph]);

  function downloadImage(format) {
    const cy = cyRef.current;
    if (!cy) return;

    // Cytoscape's jpg() doesn't support a transparent background (JPEG has
    // no alpha channel), so fall back to the app's own dark background
    // color rather than leaving it default-white for that format only.
    const options = { full: true, scale: 2, bg: format === "jpg" ? "#0f1115" : undefined };
    const dataUrl = format === "jpg" ? cy.jpg(options) : cy.png(options);

    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = `identity_graph.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  if (!graph || graph.nodes.length === 0) {
    return <p className="muted">No aliases ingested yet for this case.</p>;
  }

  return (
    <div className="graph-container">
      <div className="graph-export-buttons">
        <button className="secondary" onClick={() => downloadImage("png")}>
          Export PNG
        </button>
        <button className="secondary" onClick={() => downloadImage("jpg")}>
          Export JPG
        </button>
      </div>
      <CytoscapeComponent
        elements={elements}
        style={{ width: "100%", height: "500px" }}
        layout={{ name: "cose", animate: false }}
        cy={(cyInstance) => { cyRef.current = cyInstance; }}
        stylesheet={[
          {
            selector: "node",
            style: {
              label: "data(label)",
              "background-color": "#212529",
              color: "#fff",
              "font-size": 11,
              "text-valign": "center",
              "text-halign": "center",
              "text-outline-width": 2,
              "text-outline-color": "#212529",
              width: 46,
              height: 46,
            },
          },
          {
            selector: "edge",
            style: {
              width: (ele) => 1 + (ele.data("confidence") || 0.5) * 4,
              "line-color": "data(color)",
              "curve-style": "bezier",
              label: "data(label)",
              "font-size": 9,
              color: "#495057",
              "text-background-color": "#fff",
              "text-background-opacity": 0.8,
            },
          },
        ]}
      />
      <div className="graph-legend">
        {Object.entries(TYPE_COLORS).map(([type, color]) => (
          <span key={type} className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: color }} />
            {type.replace(/_/g, " ")}
          </span>
        ))}
      </div>
    </div>
  );
}
