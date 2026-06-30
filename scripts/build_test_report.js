const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  LevelFormat, Footer, PageNumber,
} = require("docx");

const CONTENT_W = 9360;
const gb = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: gb, bottom: gb, left: gb, right: gb };
const cm = { top: 60, bottom: 60, left: 110, right: 110 };
const HEAD = "D9E2EC", ALT = "F2F5F8";

function tc(t, w, o = {}) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, margins: cm,
    shading: { fill: o.fill || "FFFFFF", type: ShadingType.CLEAR },
    children: [new Paragraph({ alignment: o.align || AlignmentType.LEFT,
      children: [new TextRun({ text: String(t), bold: !!o.bold, size: 18 })] })],
  });
}
function table(widths, rows, rightFrom = 1) {
  return new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((cells, ri) => new TableRow({ tableHeader: ri === 0,
      children: cells.map((c, ci) => tc(c, widths[ci], {
        bold: ri === 0, fill: ri === 0 ? HEAD : (ri % 2 === 0 ? ALT : "FFFFFF"),
        align: ci >= rightFrom ? AlignmentType.RIGHT : AlignmentType.LEFT })) })) });
}
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const P = (t) => new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: t, size: 22 })] });
const BUL = (t) => new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: 60 }, children: [new TextRun({ text: t, size: 22 })] });
const NUM = (t) => new Paragraph({ numbering: { reference: "s", level: 0 }, spacing: { after: 60 }, children: [new TextRun({ text: t, size: 22 })] });
const CODE = (t) => new Paragraph({ spacing: { after: 30 }, shading: { fill: "F0F0F0", type: ShadingType.CLEAR }, children: [new TextRun({ text: t, font: "Consolas", size: 17 })] });

// mean ms, 64-byte payload, by agent count and mode (from docs/evidence)
const hdr3 = ["Agents", "sequential", "concurrent", "parallel"];
const slimPrim = table([1700, 2553, 2553, 2554], [hdr3,
  ["5", "0.070", "0.349", "0.174"], ["10", "0.064", "0.753", "0.104"], ["20", "0.073", "1.819", "0.699"]]);
const cell3 = table([1700, 2553, 2553, 2554], [hdr3,
  ["5", "0.431", "1.757", "1.526"], ["10", "0.220", "2.799", "1.820"], ["20", "0.229", "3.011", "2.160"]]);
const cell4 = table([1700, 2553, 2553, 2554], [hdr3,
  ["5", "0.159", "0.913", "1.080"], ["10", "0.137", "1.603", "1.272"], ["20", "0.132", "3.892", "2.210"]]);
const cell1 = table([2340, 3510, 3510], [["Agents", "sequential", "concurrent"],
  ["5", "3.074", "5.967"], ["10", "4.073", "18.927"], ["20", "7.448", "58.850"]]);
const cell2 = table([2340, 3510, 3510], [["Agents", "sequential", "concurrent"],
  ["5", "9.693", "19.669"], ["10", "11.939", "45.821"], ["20", "18.549", "148.341"]]);

const cellsTbl = table([1300, 3000, 2000, 3060], [
  ["Cell", "Transport", "Node", "Evidence file"],
  ["1", "A2A, no SLIM", "none", "a2a_http_mesh_sweep.json"],
  ["2", "A2A over SLIM", "slim:1.0.0", "a2a_slim_mesh_sweep.json"],
  ["3", "HTTP, no SLIM", "none", "http_mesh_sweep_parallel.json"],
  ["4", "HTTP over SLIM", "slim:1.3.0", "http_slim_mesh_sweep.json"],
]);

const deliv = table([2600, 2200, 2280, 2280], [
  ["Config (per run)", "Sent", "Delivered", "Loss"],
  ["5 agents x rounds", "60", "60", "0"],
  ["10 agents x rounds", "270", "270", "0"],
  ["20 agents x rounds", "1140", "1140", "0"],
]);

const httpVs = table([1700, 2553, 2553, 2554], [
  ["Agents", "HTTP no SLIM", "HTTP over SLIM", "Faster by"],
  ["5", "0.431", "0.159", "63 %"], ["10", "0.220", "0.137", "38 %"], ["20", "0.229", "0.132", "42 %"]]);
const a2aVs = table([1700, 2553, 2553, 2554], [
  ["Agents", "A2A no SLIM", "A2A over SLIM", "Slower by"],
  ["5", "3.074", "9.693", "3.2x"], ["10", "4.073", "11.939", "2.9x"], ["20", "7.448", "18.549", "2.5x"]]);

// Resource usage (measured with docker stats and ps during representative loads).
const resTbl = table([3060, 2100, 2100, 2100], [
  ["Component", "Memory", "CPU", "Bottleneck?"],
  ["SLIM node (broker)", "6-17 MB", "0-68% of 1 core", "No"],
  ["Client process, HTTP/SLIM", "~44 MB each", "shares host cores", "Yes (CPU)"],
  ["Client process, A2A", "~136 MB each", "shares host cores", "Yes (CPU+mem)"],
  ["Loopback network", "KB-scale", "negligible", "No"],
]);
const cpuTbl = table([2400, 2400, 4560], [
  ["Mode", "Cores used", "Note"],
  ["Sequential", "~1.5", "1 Python thread plus SLIM Rust runtime; GIL-bound"],
  ["Concurrent (threads)", "~1.5 effective", "GIL serializes Python; OS thread limit near 80 agents"],
  ["Parallel (processes)", "up to all 12", "true parallelism; host hits 0% idle; OS time-slices beyond core count"],
]);

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: "Arial", color: "1F3864" },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "2E5496" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] },
    { reference: "s", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "SLIM Full-Mesh Benchmark — Test Report — ", size: 16, color: "888888" }),
        new TextRun({ children: ["Page ", PageNumber.CURRENT], size: 16, color: "888888" })] })] }) },
    children: [
      new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "SLIM Full-Mesh Benchmark", bold: true, size: 40, font: "Arial", color: "1F3864" })] }),
      new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "Test Report", size: 26, color: "2E5496" })] }),
      new Paragraph({ spacing: { after: 240 }, border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "2E5496", space: 1 } },
        children: [new TextRun({ text: "Repository slim-benchmarks  ·  branch feat/full-mesh-scale-bench", size: 18, color: "666666" })] }),

      H1("1. Purpose and scope"),
      P("This report records the testing of the four-cell full-mesh transport benchmark: what was tested, how each test was validated, the measured results, and the issues found and fixed during testing. Every cell is a full mesh where each agent exchanges a message with every other agent. Two protocols (A2A, HTTP) are each tested with and without SLIM, giving four cells."),

      H1("2. Test environment"),
      BUL("Machine: Apple MacBook Pro (Mac16,8), 12 CPU cores, 24 GB RAM, macOS."),
      BUL("HTTP and SLIM mesh cells (3, 4): Python 3.12 (.venv-mesh), slim-bindings 1.3.0, node ghcr.io/agntcy/slim:1.3.0."),
      BUL("A2A cells (1, 2): Python 3.13 (.venv-a2a), agntcy-app-sdk 0.5.1, a2a-sdk 0.3.20, slim-bindings 1.1.1, node ghcr.io/agntcy/slim:1.0.0 with the Aether server config."),
      BUL("All runs are loopback on one machine, so latencies are a lower bound; comparisons between cells remain valid."),

      H1("3. Test matrix"),
      cellsTbl,

      H1("4. Test method"),
      P("Each agent is a real participant. For HTTP it is an HTTP server with a kept-alive connection to every peer; for the SLIM mesh it is a slim-bindings app holding a point-to-point session to every peer; for A2A it is an echo A2A agent (server plus client) running in its own process. Sessions and connections are opened once in a warm phase, so the timer measures the send path, not setup."),
      P("Each cell is exercised in up to three execution modes:"),
      BUL("Sequential: one message in flight at a time (latency floor)."),
      BUL("Concurrent: every agent fans out to all peers at once using threads."),
      BUL("Parallel: one operating-system process per agent (true parallelism); applied to cells 3 and 4 and the SLIM mesh primitive. A2A cells already run process per agent."),
      P("Message count for N agents is N x (N-1) per round. Pass criterion for every run: receivers count messages and the total reconciles exactly against messages sent, with zero loss."),

      H1("5. Delivery verification"),
      P("Every configuration across all five sweeps reconciled sent against delivered with no loss. Representative counts per agent size:"),
      deliv,
      P("Result: 100 percent delivery in every configuration and every mode tested."),

      H1("6. Latency results"),
      P("Per-message latency, mean milliseconds, 64-byte payload. Lower is better."),
      H2("6.1 SLIM mesh primitive (point-to-point unicast)"),
      slimPrim,
      H2("6.2 Cell 3 — HTTP, no SLIM"),
      cell3,
      H2("6.3 Cell 4 — HTTP over SLIM"),
      cell4,
      H2("6.4 Cell 1 — A2A, no SLIM (round trip)"),
      cell1,
      H2("6.5 Cell 2 — A2A over SLIM (round trip)"),
      cell2,

      H1("7. Cross-cell comparison"),
      H2("7.1 HTTP with vs without SLIM (sequential round trip)"),
      httpVs,
      P("HTTP over SLIM is faster than direct HTTP, about 42 percent at 20 agents, consistent with the previously reported figure near 33 percent."),
      H2("7.2 A2A with vs without SLIM (sequential round trip)"),
      a2aVs,
      P("On this single machine A2A over SLIM is slower than A2A without SLIM, because the SLIM RPC and per-call session handshake add fixed overhead that the cheap loopback HTTP path does not pay. The SLIM benefit for A2A is expected at larger scale or over a real network, which is follow-up work."),

      H1("8. Resource usage and bottleneck"),
      P("Resource usage was sampled with docker stats (node container) and ps and top (host and client processes) during representative loads on the 12-core, 24 GB machine."),
      resTbl,
      P("Across modes, client CPU usage tracks how the work spreads over cores:"),
      cpuTbl,
      P("Findings:"),
      BUL("The SLIM node is not the bottleneck. It stays light, tens of megabytes of memory and at most about one core, even under the heaviest concurrent fan-out."),
      BUL("The network is not the bottleneck. Traffic is loopback and totals only kilobytes; it is never the limiting factor in these runs."),
      BUL("Client-side CPU is the primary bottleneck. In sequential and thread-concurrent modes the Python interpreter lock caps useful work at roughly 1.5 cores regardless of agent count; only the process-per-agent parallel mode uses all cores, at which point the host reaches 0 percent idle."),
      BUL("At higher agent counts the limit shifts to host memory and process or thread count. Each HTTP/SLIM agent process is about 44 MB and each A2A agent process is about 136 MB, so A2A becomes memory-bound near 50 agents on 24 GB. The thread-concurrent mode separately hits the operating-system thread limit and fails to start new threads at around 80 agents, which is why scaling past that point uses the sequential or parallel modes."),

      H1("9. Issues found and fixed during testing"),
      BUL("Process-parallel SLIM mesh failed with 'no matching route' until the sender declared a route to each peer (set_route) before opening the session; the single-connection thread model did not need this."),
      BUL("Thread-based concurrent mode showed inflated p99 tails (HTTP up to 63 ms at 20 agents) due to the Python interpreter lock; the process-parallel mode removed this (p99 about 3.5 ms), confirming the tail was a lock artifact, not transport."),
      BUL("A2A stack failed to start ('Expected UnaryUnaryHandler subclass') under loosely resolved dependencies; pinning to the lockfile versions (agntcy-app-sdk 0.5.1, slim-bindings 1.1.1, a2a-sdk 0.3.20) fixed it."),
      BUL("A2A client and server in the same process failed the SLIM handshake because the client reused the server connection; running them as separate processes (the mesh topology) resolved it."),

      H1("10. How to reproduce"),
      NUM("Start the SLIM node for the cell under test (1.3.0 for cells 3/4, 1.0.0 with the Aether config for cell 2)."),
      NUM("Run the cell's sweep, for example HTTP over SLIM:"),
      CODE("PYTHONPATH=. .venv-mesh/bin/python http_slim_mesh_benchmark.py --sweep \\"),
      CODE("  --agents-list 5,10,20 --payloads 64,512 --rounds 3 \\"),
      CODE("  --output docs/evidence/http_slim_mesh_sweep.json"),
      NUM("Each runner prints sent vs delivered per row and writes the evidence JSON used in this report."),

      H1("11. Limitations"),
      BUL("Loopback on one machine: latencies are a lower bound and the network is not exercised."),
      BUL("True simultaneity caps at the core count (12); larger agent counts are partly time-sliced."),
      BUL("SLIM measures a one-way publish to confirmed delivery while HTTP and A2A measure a full round trip; aligning the measurement basis is open."),
      BUL("A2A cells use an echo agent, so they measure transport only, not semantic-negotiation convergence."),
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(process.argv[2], buf); console.log("wrote", process.argv[2]); });
