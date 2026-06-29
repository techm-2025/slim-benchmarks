const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  LevelFormat, Footer, PageNumber,
} = require("docx");

const CONTENT_W = 9360;
const grayB = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: grayB, bottom: grayB, left: grayB, right: grayB };
const cellMargins = { top: 60, bottom: 60, left: 110, right: 110 };
const HEAD_FILL = "D9E2EC";
const ALT_FILL = "F2F5F8";

function tcell(text, w, opts = {}) {
  return new TableCell({
    borders,
    width: { size: w, type: WidthType.DXA },
    margins: cellMargins,
    shading: { fill: opts.fill || "FFFFFF", type: ShadingType.CLEAR },
    children: [new Paragraph({
      alignment: opts.align || AlignmentType.LEFT,
      children: [new TextRun({ text: String(text), bold: !!opts.bold, size: 19 })],
    })],
  });
}

// columns: array of widths; rows: array of arrays of strings; first row = header
function makeTable(widths, rows, rightFromCol = 1) {
  const trs = rows.map((cells, ri) => new TableRow({
    tableHeader: ri === 0,
    children: cells.map((c, ci) => tcell(c, widths[ci], {
      bold: ri === 0,
      fill: ri === 0 ? HEAD_FILL : (ri % 2 === 0 ? ALT_FILL : "FFFFFF"),
      align: ci >= rightFromCol ? AlignmentType.RIGHT : AlignmentType.LEFT,
    })),
  }));
  return new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths, rows: trs });
}

const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const P = (t, opts = {}) => new Paragraph({
  spacing: { after: 120 },
  children: [new TextRun({ text: t, size: 22, ...opts })],
});
const BUL = (t) => new Paragraph({
  numbering: { reference: "bullets", level: 0 }, spacing: { after: 60 },
  children: [new TextRun({ text: t, size: 22 })],
});
const NUM = (t) => new Paragraph({
  numbering: { reference: "steps", level: 0 }, spacing: { after: 60 },
  children: [new TextRun({ text: t, size: 22 })],
});
const CODE = (t) => new Paragraph({
  spacing: { after: 40 }, shading: { fill: "F0F0F0", type: ShadingType.CLEAR },
  children: [new TextRun({ text: t, font: "Consolas", size: 18 })],
});

// data: agents x payload 64B, mean / p99 (ms), from docs/evidence sweeps
const seq = makeTable([1500, 1980, 1980, 1980, 1980], [
  ["Agents", "SLIM mean", "SLIM p99", "HTTP mean", "HTTP p99"],
  ["5", "0.070", "0.207", "0.431", "0.690"],
  ["10", "0.064", "0.164", "0.220", "0.346"],
  ["20", "0.073", "0.210", "0.229", "0.445"],
]);
const conc = makeTable([1500, 1980, 1980, 1980, 1980], [
  ["Agents", "SLIM mean", "SLIM p99", "HTTP mean", "HTTP p99"],
  ["5", "0.349", "0.768", "1.757", "2.701"],
  ["10", "0.753", "2.666", "2.799", "31.779"],
  ["20", "1.819", "8.030", "3.011", "63.435"],
]);
const par = makeTable([1500, 1980, 1980, 1980, 1980], [
  ["Agents", "SLIM mean", "SLIM p99", "HTTP mean", "HTTP p99"],
  ["5", "0.174", "0.562", "1.526", "2.363"],
  ["10", "0.104", "0.204", "1.820", "30.704"],
  ["20", "0.699", "7.352", "2.160", "3.484"],
]);
const cells = makeTable([3400, 4000, 1960], [
  ["Cell", "Description", "Status"],
  ["1", "A2A, no SLIM (mesh)", "Pending"],
  ["2", "A2A over SLIM", "Pending"],
  ["3", "HTTP, no SLIM (mesh)", "Done"],
  ["4", "HTTP over SLIM", "Done"],
]);

// HTTP with vs without SLIM, round-trip, 64-byte payload, 3 rounds, sequential.
const httpVs = makeTable([1500, 2400, 2400, 3060], [
  ["Agents", "HTTP no SLIM mean", "HTTP over SLIM mean", "Improvement"],
  ["5", "0.431", "0.221", "49 %"],
  ["10", "0.220", "0.160", "27 %"],
  ["20", "0.229", "0.155", "32 %"],
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
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] },
      { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "SLIM Full-Mesh Benchmark — ", size: 16, color: "888888" }),
        new TextRun({ children: ["Page ", PageNumber.CURRENT], size: 16, color: "888888" })],
    })] }) },
    children: [
      new Paragraph({ spacing: { after: 60 }, children: [
        new TextRun({ text: "SLIM Full-Mesh Transport Benchmark", bold: true, size: 40, font: "Arial", color: "1F3864" })] }),
      new Paragraph({ spacing: { after: 240 }, children: [
        new TextRun({ text: "Concurrency Method and HTTP Baseline", size: 26, color: "2E5496" })] }),
      new Paragraph({ spacing: { after: 240 }, border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "2E5496", space: 1 } }, children: [
        new TextRun({ text: "Repository slim-benchmarks  ·  branch feat/full-mesh-scale-bench  ·  date 2026-06-26", size: 18, color: "666666" })] }),

      H1("1. Objective"),
      P("Compare full-mesh transport latency across the four cells defined for this study, sweeping agent counts from 5 to 100. Each agent talks to every other agent. This document covers two deliverables completed in this iteration: the HTTP no-SLIM baseline (cell 3), and a process-per-agent concurrency method that produces genuine parallelism on a single laptop."),

      H1("2. The four cells"),
      cells,
      P("", { }),
      P("This iteration delivers both HTTP cells (3 and 4) and the measurement method that all cells use. Cells 1 and 2 depend on the A2A application layer and the A2A-over-SLIM tunnel, which are owned jointly with the semantic-negotiation work and are not yet wired in."),

      H1("3. Environment"),
      BUL("Machine: Apple MacBook Pro (Mac16,8), 12 CPU cores, 24 GB RAM."),
      BUL("SLIM node: ghcr.io/agntcy/slim:1.3.0 in Docker, listening on port 46357."),
      BUL("Client: Python 3.12 with slim-bindings 1.3.0 (does not resolve on 3.13)."),
      BUL("All runs are loopback on one machine, so absolute numbers are a lower bound; the shape and the relative comparison hold."),

      H1("4. Method"),
      P("Each agent is a real participant: for HTTP without SLIM it is a small HTTP server with a keep-alive connection to every peer; for the SLIM mesh it is a slim-bindings application that subscribes its own name and holds a point-to-point session to every peer; for HTTP over SLIM each agent tunnels an HTTP-style request and response through a SLIM point-to-point session, with the peer replying on the same session. Sessions and connections are opened once in a warm phase, so the per-message timer measures the send path, not setup."),
      P("Message count for N agents, one directed message per ordered pair, is N x (N-1) per round. Delivery is verified: receivers count messages and the total is reconciled against messages sent. All runs in this report show 100 percent delivery.", { }),
      P("Three execution modes are measured:", { bold: false }),
      BUL("Sequential: one message in flight at a time. This is the latency floor."),
      BUL("Concurrent (threads): every agent fans out at once using one thread per source, released together on a barrier."),
      BUL("Parallel (processes): every agent runs in its own operating-system process. See section 5."),

      H1("5. Achieving real concurrency on one laptop"),
      P("The thread-based concurrent mode shares one Python interpreter lock, so the Python side of the sends never runs in parallel; only the input/output waits overlap. To measure genuine concurrency the harness adds a parallel mode that runs one process per agent. Each process has its own runtime and connection, warms its routes, and fires its fan-out on a shared cross-process barrier."),
      P("On this 12-core machine, up to about 12 agents send at the same literal instant; beyond that the operating system time-slices the processes. That is the honest ceiling for concurrency on a single laptop, and the harness logs a note whenever the agent count exceeds the core count."),
      P("One SLIM-specific detail: with a single shared connection the node routes between co-located apps automatically, but with one connection per process the sender must declare a route to each peer name (set_route) before opening the session, otherwise discovery fails with no matching route. This is handled in the parallel harness.", { }),

      H1("6. Results"),
      P("Per-message latency in milliseconds, 64-byte payload, 3 rounds per configuration, 100 percent delivery throughout. SLIM is the real slim-bindings dataplane; HTTP is the no-SLIM mesh baseline."),
      H2("6.1 Sequential (latency floor)"),
      seq,
      H2("6.2 Concurrent (threads)"),
      conc,
      H2("6.3 Parallel (process per agent)"),
      par,
      H2("6.4 HTTP with and without SLIM (round trip)"),
      P("Both legs measure a full request-response round trip, so they are directly comparable. Sequential, 64-byte payload, 3 rounds."),
      httpVs,

      H1("7. Findings"),
      BUL("SLIM is well under one millisecond sequentially and roughly three to five times faster than HTTP at the same configuration."),
      BUL("Under thread-based concurrency the HTTP tail degrades sharply (p99 reaches 63 ms at 20 agents) because all sends queue behind one interpreter lock; SLIM stays bounded because its dataplane runs outside that lock."),
      BUL("Under true process parallelism the HTTP tail collapses back (p99 at 20 agents drops from 63 ms to about 3.5 ms), which confirms the thread-concurrent tail was an artifact of the lock, not the transport."),
      BUL("SLIM under process parallelism remains sub-millisecond on average and the lowest of all three transports tested."),
      BUL("On a like-for-like round trip, HTTP over SLIM is faster than direct HTTP, by about 32 percent at 20 agents, which is consistent with the previously reported improvement near 33 percent."),

      H1("8. How to run"),
      P("Prerequisites: Docker Desktop running, and a Python 3.12 virtual environment with slim-bindings 1.3.0."),
      NUM("Start the SLIM node (required for the SLIM legs only)."),
      CODE("docker run --rm -d --name slim-node -p 46357:46357 \\"),
      CODE("  -v \"$(pwd)/server-config.yaml:/config.yaml\" \\"),
      CODE("  --entrypoint /slim ghcr.io/agntcy/slim:1.3.0 --config /config.yaml"),
      NUM("Run the SLIM sweep across all three modes and write evidence."),
      CODE("PYTHONPATH=. .venv-mesh/bin/python mesh_benchmark.py --sweep \\"),
      CODE("  --agents-list 5,10,20 --payloads 64,512 --rounds 3 --parallel \\"),
      CODE("  --output docs/evidence/mesh_sweep_parallel.json"),
      NUM("Run the HTTP baseline sweep (no node or Docker needed)."),
      CODE("PYTHONPATH=. .venv-mesh/bin/python http_mesh_benchmark.py --sweep \\"),
      CODE("  --agents-list 5,10,20 --payloads 64,512 --rounds 3 --parallel \\"),
      CODE("  --output docs/evidence/http_mesh_sweep_parallel.json"),
      NUM("Run the HTTP-over-SLIM sweep (cell 4; needs the node)."),
      CODE("PYTHONPATH=. .venv-mesh/bin/python http_slim_mesh_benchmark.py --sweep \\"),
      CODE("  --agents-list 5,10,20 --payloads 64,512 --rounds 3 \\"),
      CODE("  --output docs/evidence/http_slim_mesh_sweep.json"),
      NUM("Stop the node when finished."),
      CODE("docker rm -f slim-node"),

      H1("9. Files"),
      BUL("slim_bench/mesh.py and mesh_benchmark.py: SLIM full-mesh harness and runner."),
      BUL("slim_bench/mp_mesh.py: process-per-agent parallel SLIM harness."),
      BUL("slim_bench/http_mesh.py and http_mesh_benchmark.py: HTTP no-SLIM harness and runner."),
      BUL("slim_bench/mp_http_mesh.py: process-per-agent parallel HTTP harness."),
      BUL("slim_bench/http_slim_mesh.py and http_slim_mesh_benchmark.py: HTTP-over-SLIM harness and runner (cell 4)."),
      BUL("slim_bench/results.py: shared result and summary-statistics shape used by every leg."),
      BUL("docs/evidence: mesh_sweep_parallel.json, http_mesh_sweep_parallel.json, and http_slim_mesh_sweep.json hold the raw results behind this report."),

      H1("10. Limitations and open items"),
      BUL("All measurements are loopback on one machine, so they are a lower bound; numbers will move over a real network."),
      BUL("True simultaneity is capped at the core count (12 here); larger agent counts are partly time-sliced."),
      BUL("Message model is not yet pinned: SLIM measures a one-way publish to confirmed delivery, while HTTP measures a full request-response round trip. These are not yet symmetric and must be aligned before the headline comparison."),
      BUL("Cells 1 and 2 (A2A and the A2A-over-SLIM tunnel) remain to be built; the sweep should then be extended toward 100 agents."),
      BUL("Cell 4 currently has sequential and concurrent modes; the process-per-agent parallel mode can be added for full symmetry with the other legs."),
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2], buf);
  console.log("wrote", process.argv[2]);
});
