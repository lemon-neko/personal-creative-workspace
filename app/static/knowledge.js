(() => {
  const graphRoot = document.querySelector("#knowledge-graph");
  const dataNode = document.querySelector("#knowledge-graph-data");
  if (!graphRoot || !dataNode || !window.d3) return;

  const sourceData = JSON.parse(dataNode.textContent || '{"nodes":[],"edges":[]}');
  const searchInput = document.querySelector("#knowledge-search");
  const subjectSelect = document.querySelector("#knowledge-subject");
  const statusSelect = document.querySelector("#knowledge-status");
  const kindSelect = document.querySelector("#knowledge-kind");
  const resetButton = document.querySelector("#knowledge-reset");
  const inspector = document.querySelector("#knowledge-inspector");
  const emptyState = graphRoot.querySelector(".graph-empty");
  let simulation;
  let svg;
  let zoom;

  const connectedConcepts = (itemIds) => {
    const result = new Set();
    sourceData.edges.forEach((edge) => {
      if (itemIds.has(edge.source) && String(edge.target).startsWith("concept:")) {
        result.add(edge.target);
      }
      if (itemIds.has(edge.target) && String(edge.source).startsWith("concept:")) {
        result.add(edge.source);
      }
    });
    return result;
  };

  const filteredData = () => {
    const query = (searchInput?.value || "").trim().toLocaleLowerCase();
    const subject = subjectSelect?.value || "";
    const status = statusSelect?.value || "";
    const kind = kindSelect?.value || "";
    const matchesText = (node) =>
      !query || `${node.label} ${node.summary || ""}`.toLocaleLowerCase().includes(query);
    const matchesSubject = (node) =>
      !subject || (node.subjects || []).includes(subject) || node.subject === subject;

    const primaryNodes = sourceData.nodes.filter(
      (node) =>
        node.type !== "concept" &&
        matchesText(node) &&
        matchesSubject(node) &&
        (!status || node.status === status) &&
        (!kind || (kind !== "concept" && (node.type === kind || node.kind === kind))),
    );
    const itemIds = new Set(primaryNodes.map((node) => node.id));
    const attachedConcepts = connectedConcepts(itemIds);
    const conceptNodes = sourceData.nodes.filter(
      (node) =>
        node.type === "concept" &&
        (!kind || kind === "concept") &&
        matchesSubject(node) &&
        (kind === "concept" || attachedConcepts.has(node.id) || (query && matchesText(node))) &&
        (!query || matchesText(node) || attachedConcepts.has(node.id)),
    );
    const nodes = kind === "concept" ? conceptNodes : [...primaryNodes, ...conceptNodes];
    const nodeIds = new Set(nodes.map((node) => node.id));
    const edges = sourceData.edges.filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
    );
    return { nodes, edges };
  };

  const showInspector = (node, edges, nodesById) => {
    inspector.replaceChildren();
    const marker = document.createElement("span");
    marker.className = "inspector-type";
    const typeLabels = { source: "原始来源", card: "知识卡", subject: "学科地图", topic: "主题地图", concept: "概念" };
    marker.textContent = typeLabels[node.type] || node.type;
    const title = document.createElement("h3");
    title.textContent = node.label;
    const summary = document.createElement("p");
    summary.textContent = node.summary || "暂无摘要";
    const subjects = document.createElement("div");
    subjects.className = "tag-row";
    (node.subjects?.length ? node.subjects : ["未分类"]).forEach((subject) => {
      const tag = document.createElement("span");
      tag.textContent = subject;
      subjects.append(tag);
    });
    const relationTitle = document.createElement("strong");
    relationTitle.textContent = "直接关联";
    const list = document.createElement("ul");
    edges
      .filter((edge) => edge.source.id === node.id || edge.target.id === node.id)
      .slice(0, 8)
      .forEach((edge) => {
        const neighbour = edge.source.id === node.id ? edge.target : edge.source;
        const item = document.createElement("li");
        item.textContent = `${edge.label || edge.type} · ${nodesById.get(neighbour.id)?.label || neighbour.label}`;
        list.append(item);
      });
    inspector.append(marker, title, summary, subjects, relationTitle, list);
    if (node.href) {
      const link = document.createElement("a");
      link.href = node.href;
      link.textContent = "打开内容 →";
      inspector.append(link);
    }
  };

  const render = () => {
    if (simulation) simulation.stop();
    graphRoot.querySelector("svg")?.remove();
    const { nodes: rawNodes, edges: rawEdges } = filteredData();
    emptyState.hidden = rawNodes.length > 0;
    if (!rawNodes.length) return;

    const width = Math.max(graphRoot.clientWidth, 320);
    const height = Math.max(Math.min(width * 0.62, 680), 430);
    const nodes = rawNodes.map((node) => ({ ...node }));
    const edges = rawEdges.map((edge) => ({ ...edge }));
    const nodesById = new Map(nodes.map((node) => [node.id, node]));

    svg = d3
      .select(graphRoot)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img")
      .attr("aria-label", "想法与概念关系图");
    const scene = svg.append("g");
    zoom = d3
      .zoom()
      .scaleExtent([0.45, 3.5])
      .on("zoom", (event) => scene.attr("transform", event.transform));
    svg.call(zoom);

    const link = scene
      .append("g")
      .attr("class", "graph-links")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr("class", (edge) => `graph-link relation-${edge.type}`)
      .attr("stroke-width", (edge) => Math.min(1 + (edge.weight || 1) * 0.45, 3));

    const node = scene
      .append("g")
      .attr("class", "graph-nodes")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("class", (value) => `graph-node node-${value.type}`)
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", (value) => `${value.type}：${value.label}`);

    node
      .append("circle")
      .attr("r", (value) => (value.type === "concept" ? 8 + Math.min(value.count || 1, 5) : 11))
      .attr("fill", (value) => value.color || ({ source: "#7aa6ad", card: "#078fa9", subject: "#7b68a6", topic: "#d28a34", concept: "#d56879" }[value.type] || "#8b9293"))
      .attr("stroke", "#fffefa");
    node
      .append("text")
      .attr("x", 15)
      .attr("y", 4)
      .text((value) => (value.label.length > 16 ? `${value.label.slice(0, 16)}…` : value.label));

    const focusNode = (_, selected) => {
      const neighbours = new Set([selected.id]);
      edges.forEach((edge) => {
        if (edge.source.id === selected.id) neighbours.add(edge.target.id);
        if (edge.target.id === selected.id) neighbours.add(edge.source.id);
      });
      node.classed("muted", (value) => !neighbours.has(value.id));
      link.classed(
        "muted",
        (edge) => edge.source.id !== selected.id && edge.target.id !== selected.id,
      );
      showInspector(selected, edges, nodesById);
    };
    node.on("click", focusNode).on("keydown", (event, value) => {
      if (event.key === "Enter" || event.key === " ") focusNode(event, value);
    });

    const drag = d3
      .drag()
      .on("start", (event, value) => {
        if (!event.active) simulation.alphaTarget(0.24).restart();
        value.fx = value.x;
        value.fy = value.y;
      })
      .on("drag", (event, value) => {
        value.fx = event.x;
        value.fy = event.y;
      })
      .on("end", (event, value) => {
        if (!event.active) simulation.alphaTarget(0);
        value.fx = null;
        value.fy = null;
      });
    node.call(drag);

    simulation = d3
      .forceSimulation(nodes)
      .force("link", d3.forceLink(edges).id((value) => value.id).distance((edge) => edge.type === "mentions" ? 66 : 105))
      .force("charge", d3.forceManyBody().strength((value) => value.type === "concept" ? -95 : -155))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius((value) => value.type === "concept" ? 24 : 34))
      .on("tick", () => {
        link
          .attr("x1", (edge) => edge.source.x)
          .attr("y1", (edge) => edge.source.y)
          .attr("x2", (edge) => edge.target.x)
          .attr("y2", (edge) => edge.target.y);
        node.attr("transform", (value) => `translate(${value.x},${value.y})`);
      });
  };

  let searchTimer;
  searchInput?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(render, 220);
  });
  [subjectSelect, statusSelect, kindSelect].forEach((control) =>
    control?.addEventListener("change", render),
  );
  resetButton?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    if (subjectSelect) subjectSelect.value = "";
    if (statusSelect) statusSelect.value = "";
    if (kindSelect) kindSelect.value = "";
    render();
  });

  render();
  if (window.ResizeObserver) {
    let resizeTimer;
    new ResizeObserver(() => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(render, 160);
    }).observe(graphRoot);
  }
})();
