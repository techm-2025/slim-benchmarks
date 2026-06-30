const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType, LevelFormat, Footer, PageNumber,
} = require("docx");

const W = 9360;
const gb = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: gb, bottom: gb, left: gb, right: gb };
const cm = { top: 60, bottom: 60, left: 110, right: 110 };
function tc(t, w, o = {}) {
  return new TableCell({ borders, width: { size: w, type: WidthType.DXA }, margins: cm,
    shading: { fill: o.fill || "FFFFFF", type: ShadingType.CLEAR },
    children: [new Paragraph({ alignment: o.align || AlignmentType.LEFT, children: [new TextRun({ text: String(t), bold: !!o.bold, size: 19 })] })] });
}
function table(widths, rows) {
  return new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((cells, ri) => new TableRow({ tableHeader: ri === 0,
      children: cells.map((c, ci) => tc(c, widths[ci], { bold: ri === 0, fill: ri === 0 ? "D9E2EC" : (ri % 2 === 0 ? "F2F5F8" : "FFFFFF") })) })) });
}
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const P = (t) => new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: t, size: 22 })] });
const BUL = (t) => new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: 60 }, children: [new TextRun({ text: t, size: 22 })] });

const cells = table([1200, 4100, 4060], [
  ["Cell", "Description", "Owner"],
  ["1", "A2A, no SLIM (mesh)", "Saify (apply this spec)"],
  ["2", "A2A over SLIM", "Saify (apply this spec)"],
  ["3", "HTTP, no SLIM (mesh)", "Reference (this spec)"],
  ["4", "HTTP over SLIM", "Reference (this spec)"],
]);

const sweep = table([3120, 6240], [
  ["Parameter", "Value"],
  ["Agent counts", "5, 10, 15, 20, ... (extend toward 100 as resources allow)"],
  ["Payload sizes", "64 and 512 bytes"],
  ["Rounds per config", "3 (pool for stable percentiles)"],
  ["Modes", "sequential, concurrent, parallel (process per agent)"],
]);

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: "1F3864" }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 } },
    ],
  },
  numbering: { config: [{ reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Benchmark Methodology Specification — ", size: 16, color: "888888" }), new TextRun({ children: ["Page ", PageNumber.CURRENT], size: 16, color: "888888" })] })] }) },
    children: [
      new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "Full-Mesh Benchmark", bold: true, size: 36, font: "Arial", color: "1F3864" })] }),
      new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Methodology Specification", size: 24, color: "2E5496" })] }),
      new Paragraph({ spacing: { after: 200 }, border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "2E5496", space: 1 } },
        children: [new TextRun({ text: "For consistent measurement across all four cells (HTTP and A2A, with and without SLIM)", size: 18, color: "666666" })] }),

      H1("1. Purpose"),
      P("This document fixes one measurement methodology so that all four cells are produced the same way and the results are directly comparable. The HTTP cells are the reference; the same methodology must be applied to the A2A cells. The four cells:"),
      cells,

      H1("2. Topology"),
      BUL("Each agent runs in its own operating-system process, one identity per process."),
      BUL("All agents run on a single machine for now. This is acknowledged to be OS-scheduled rather than truly parallel: agents on the same core share CPU time, so only as many agents as there are cores run at one instant. This is acceptable as long as the same setup is used for every cell. A later run with agents on separate compute instances or cloud pods would be the real-life setup."),
      BUL("Full mesh: every agent exchanges with every other agent. For N agents there are N x (N-1) directed pairs per round."),

      H1("3. Agent"),
      BUL("Use a trivial echo agent (no LLM, no semantic negotiation) so the measurement reflects transport only."),
      BUL("Each agent acts as both server (answers peers) and client (sends to peers)."),

      H1("4. Measurement unit"),
      BUL("One measured unit is a full request to response round trip: send a request to a peer and wait for its reply."),
      BUL("Sessions and connections are opened once in a warm phase; the timer measures only the send/receive path, not setup."),
      BUL("Record per-message latency (mean, p95, p99) and the wall time per round."),

      H1("5. Execution modes and sweep"),
      P("Run every configuration in three modes and sweep agent count and payload size:"),
      sweep,

      H1("6. Pass criterion"),
      BUL("Receivers count messages and the total is reconciled exactly against messages sent."),
      BUL("A run is valid only at 100 percent delivery (sent equals received, zero loss)."),

      H1("7. Environment to record"),
      BUL("Machine: CPU core count and memory (this affects the parallel ceiling)."),
      BUL("Node image and version, and the client library versions, pinned to the project lockfile."),
      BUL("Note that all runs are loopback on one machine, so latencies are a lower bound."),

      H1("8. Outputs"),
      BUL("A JSON evidence file per cell with the full sweep (sent, received, mean, p95, p99, wall time)."),
      BUL("A short results table per cell, and the with-vs-without-SLIM comparison."),
      BUL("Resource notes: node CPU and memory, client CPU and memory, and the observed bottleneck."),

      H1("9. Reference implementation"),
      BUL("HTTP cells: http_mesh_benchmark.py (cell 3) and http_slim_mesh_benchmark.py (cell 4)."),
      BUL("A2A cells, already built to this spec for reference: a2a_http_mesh_benchmark.py (cell 1) and a2a_slim_mesh_benchmark.py (cell 2)."),
      BUL("Repository slim-benchmarks, branch feat/full-mesh-scale-bench. Saify should apply the same topology, agent, measurement unit, modes and pass criterion to the A2A cells."),
    ],
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(process.argv[2], b); console.log("wrote", process.argv[2]); });
