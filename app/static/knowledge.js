(() => {
  const graphRoot = document.querySelector("#knowledge-graph");
  const dataNode = document.querySelector("#knowledge-graph-data");
  if (!graphRoot || !dataNode || !window.d3) return;

  const sourceData = JSON.parse(dataNode.textContent || '{"nodes":[],"edges":[],"sources":[],"source_edges":[]}');
  const searchInput = document.querySelector("#knowledge-search");
  const subjectSelect = document.querySelector("#knowledge-subject");
  const statusSelect = document.querySelector("#knowledge-status");
  const relationSelect = document.querySelector("#knowledge-relation");
  const resetButton = document.querySelector("#knowledge-reset");
  const inspector = document.querySelector("#knowledge-inspector");
  const emptyState = graphRoot.querySelector(".graph-empty");
  const expandedCards = new Set();
  let simulation;

  const typeLabels = { source: "原始来源", card: "知识卡", subject: "学科地图", topic: "主题地图" };
  const relationLabels = {
    child_of: "上级", belongs_to: "归属", derived_from: "来源",
    related: "相关", extends: "延伸", supports: "支持",
    contrasts: "对照", superseded_by: "替代",
  };
  const hashNumber = (value) => {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return Math.abs(hash >>> 0);
  };

  const filteredData = () => {
    const query = (searchInput?.value || "").trim().toLocaleLowerCase();
    const subject = subjectSelect?.value || "";
    const status = statusSelect?.value || "active";
    const relation = relationSelect?.value || "";
    const matchesText = (node) =>
      !query || (node.label + " " + (node.summary || "") + " " + (node.concepts || []).join(" "))
        .toLocaleLowerCase().includes(query);
    const matchesSubject = (node) =>
      !subject || (node.subjects || []).includes(subject) || node.label === subject;
    const coreNodes = sourceData.nodes.filter((node) => {
      if (!matchesText(node) || !matchesSubject(node)) return false;
      return !(node.type === "card" && status && node.status !== status);
    });
    let nodeIds = new Set(coreNodes.map((node) => node.id));
    let edges = sourceData.edges.filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
    );
    if (relation) {
      const semantic = edges.filter((edge) => edge.type === relation);
      const relatedIds = new Set(semantic.flatMap((edge) => [edge.source, edge.target]));
      sourceData.edges.forEach((edge) => {
        if (["child_of", "belongs_to"].includes(edge.type) &&
            (relatedIds.has(edge.source) || relatedIds.has(edge.target))) {
          relatedIds.add(edge.source);
          relatedIds.add(edge.target);
        }
      });
      nodeIds = relatedIds;
      edges = sourceData.edges.filter(
        (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target) &&
          (edge.type === relation || ["child_of", "belongs_to"].includes(edge.type)),
      );
    }
    const visibleCore = coreNodes.filter((node) => nodeIds.has(node.id));
    const visibleSources = sourceData.sources.filter((source) =>
      sourceData.source_edges.some(
        (edge) => expandedCards.has(edge.source) && nodeIds.has(edge.source) && edge.target === source.id,
      ),
    );
    const sourceIds = new Set(visibleSources.map((node) => node.id));
    const sourceEdges = sourceData.source_edges.filter(
      (edge) => expandedCards.has(edge.source) && nodeIds.has(edge.source) && sourceIds.has(edge.target),
    );
    return { nodes: [...visibleCore, ...visibleSources], edges: [...edges, ...sourceEdges] };
  };

  const showInspector = (node, edges, nodesById) => {
    inspector.replaceChildren();
    const marker = document.createElement("span");
    marker.className = "inspector-type";
    marker.textContent = typeLabels[node.type] || node.type;
    const title = document.createElement("h3");
    title.textContent = node.label;
    const summary = document.createElement("p");
    summary.textContent = node.summary || "暂无摘要";
    inspector.append(marker, title, summary);
    if (node.concepts?.length) {
      const concepts = document.createElement("div");
      concepts.className = "tag-row";
      node.concepts.forEach((value) => {
        const tag = document.createElement("span");
        tag.textContent = value;
        concepts.append(tag);
      });
      inspector.append(concepts);
    }
    const related = edges.filter(
      (edge) => edge.source.id === node.id || edge.target.id === node.id,
    );
    if (related.length) {
      const relationTitle = document.createElement("strong");
      relationTitle.textContent = "当前可见关联";
      const list = document.createElement("ul");
      related.slice(0, 10).forEach((edge) => {
        const neighbour = edge.source.id === node.id ? edge.target : edge.source;
        const item = document.createElement("li");
        item.textContent = (relationLabels[edge.type] || edge.type) + " · " +
          (nodesById.get(neighbour.id)?.label || neighbour.label);
        list.append(item);
      });
      inspector.append(relationTitle, list);
    }
    if (node.type === "card" && node.source_count) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button graph-source-toggle";
      button.textContent = expandedCards.has(node.id)
        ? "收起原始来源" : "展开 " + node.source_count + " 条原始来源";
      button.addEventListener("click", () => {
        if (expandedCards.has(node.id)) expandedCards.delete(node.id);
        else expandedCards.add(node.id);
        render(node.id);
      });
      inspector.append(button);
    }
    if (node.href) {
      const link = document.createElement("a");
      link.href = node.href;
      link.textContent = "打开详情 →";
      inspector.append(link);
    }
  };

  const render = (selectedId = "") => {
    if (simulation) simulation.stop();
    graphRoot.querySelector("svg")?.remove();
    const data = filteredData();
    emptyState.hidden = data.nodes.length > 0;
    if (!data.nodes.length) return;
    const width = Math.max(graphRoot.clientWidth, 320);
    const height = Math.max(Math.min(width * 0.62, 680), 440);
    const clusterIds = [...new Set(
      data.nodes.filter((node) => node.type !== "source").map((node) => node.cluster || node.id),
    )].sort();
    const clusterCenters = new Map(clusterIds.map((cluster, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(clusterIds.length, 1) - Math.PI / 2;
      const radius = Math.min(width, height) * (clusterIds.length > 1 ? 0.3 : 0);
      return [cluster, { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius }];
    }));
    const nodes = data.nodes.map((node) => {
      const seed = hashNumber(node.id);
      const parentEdge = data.edges.find((edge) => edge.type === "derived_from" && edge.target === node.id);
      const parent = parentEdge ? data.nodes.find((value) => value.id === parentEdge.source) : null;
      const center = clusterCenters.get(node.cluster || parent?.cluster) || { x: width / 2, y: height / 2 };
      const angle = ((seed % 360) * Math.PI) / 180;
      const spread = node.type === "subject" ? 0 : 42 + (seed % 80);
      return { ...node, x: center.x + Math.cos(angle) * spread, y: center.y + Math.sin(angle) * spread };
    });
    const edges = data.edges.map((edge) => ({ ...edge }));
    const nodesById = new Map(nodes.map((node) => [node.id, node]));
    const svg = d3.select(graphRoot).append("svg")
      .attr("viewBox", "0 0 " + width + " " + height)
      .attr("role", "img").attr("aria-label", "核心知识关系图");
    const scene = svg.append("g");
    svg.call(d3.zoom().scaleExtent([0.45, 3.5])
      .on("zoom", (event) => scene.attr("transform", event.transform)));
    const link = scene.append("g").attr("class", "graph-links").selectAll("line")
      .data(edges).join("line").attr("class", (edge) => "graph-link relation-" + edge.type);
    const node = scene.append("g").attr("class", "graph-nodes").selectAll("g")
      .data(nodes).join("g").attr("class", (value) => "graph-node node-" + value.type)
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", (value) => (typeLabels[value.type] || value.type) + "：" + value.label);
    node.append("circle")
      .attr("r", (value) => ({ subject: 17, topic: 13, card: 10, source: 7 }[value.type] || 9))
      .attr("fill", (value) => ({ subject: "#725a9a", topic: "#d3943a", card: "#078fa9", source: "#8d9998" }[value.type] || "#8b9293"))
      .attr("stroke", "#fffefa");
    node.append("text").attr("x", (value) => value.type === "subject" ? 22 : 16).attr("y", 4)
      .text((value) => value.label.length > 16 ? value.label.slice(0, 16) + "…" : value.label);
    const focusNode = (_, selected) => {
      const neighbours = new Set([selected.id]);
      edges.forEach((edge) => {
        if (edge.source.id === selected.id) neighbours.add(edge.target.id);
        if (edge.target.id === selected.id) neighbours.add(edge.source.id);
      });
      node.classed("muted", (value) => !neighbours.has(value.id));
      link.classed("muted", (edge) => edge.source.id !== selected.id && edge.target.id !== selected.id);
      showInspector(selected, edges, nodesById);
    };
    node.on("click", focusNode).on("keydown", (event, value) => {
      if (event.key === "Enter" || event.key === " ") focusNode(event, value);
    });
    node.call(d3.drag()
      .on("start", (event, value) => {
        if (!event.active) simulation.alphaTarget(0.2).restart();
        value.fx = value.x; value.fy = value.y;
      })
      .on("drag", (event, value) => { value.fx = event.x; value.fy = event.y; })
      .on("end", (event, value) => {
        if (!event.active) simulation.alphaTarget(0);
        value.fx = null; value.fy = null;
      }));
    simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges).id((value) => value.id)
        .distance((edge) => edge.type === "derived_from" ? 55 : edge.type === "belongs_to" ? 78 : 105)
        .strength((edge) => ["child_of", "belongs_to"].includes(edge.type) ? 0.65 : 0.35))
      .force("charge", d3.forceManyBody().strength((value) => value.type === "subject" ? -260 : -130))
      .force("x", d3.forceX((value) => (clusterCenters.get(value.cluster) || { x: width / 2 }).x)
        .strength((value) => value.type === "subject" ? 0.35 : 0.09))
      .force("y", d3.forceY((value) => (clusterCenters.get(value.cluster) || { y: height / 2 }).y)
        .strength((value) => value.type === "subject" ? 0.35 : 0.09))
      .force("collision", d3.forceCollide().radius((value) => value.type === "subject" ? 48 : 34))
      .alphaDecay(0.045)
      .on("tick", () => {
        link.attr("x1", (edge) => edge.source.x).attr("y1", (edge) => edge.source.y)
          .attr("x2", (edge) => edge.target.x).attr("y2", (edge) => edge.target.y);
        node.attr("transform", (value) => "translate(" + value.x + "," + value.y + ")");
      });
    if (selectedId && nodesById.has(selectedId)) {
      window.setTimeout(() => showInspector(nodesById.get(selectedId), edges, nodesById), 0);
    }
  };

  let searchTimer;
  searchInput?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => render(), 180);
  });
  [subjectSelect, statusSelect, relationSelect].forEach(
    (control) => control?.addEventListener("change", () => render()),
  );
  resetButton?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    if (subjectSelect) subjectSelect.value = "";
    if (statusSelect) statusSelect.value = "active";
    if (relationSelect) relationSelect.value = "";
    expandedCards.clear();
    render();
  });
  render();
  if (window.ResizeObserver) {
    let resizeTimer;
    new ResizeObserver(() => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => render(), 160);
    }).observe(graphRoot);
  }
})();
