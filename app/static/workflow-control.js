(() => {
    const $ = (id) => document.getElementById(`control-${id}`);
    if (!document.getElementById('workflow-control')) return;
    const el = (tag, value, className) => {
        const node = document.createElement(tag);
        if (value !== undefined && value !== null) node.textContent = value;
        if (className) node.className = className;
        return node;
    };
    const button = (label, action, className) => {
        const node = el('button', label, className);
        node.type = 'button';
        node.addEventListener('click', action);
        return node;
    };
    const anchor = (label, url) => {
        const node = el('a', label);
        node.href = url;
        return node;
    };
    const itemLink = (id, label = '打开工作项') => anchor(label, `/workflow/items/${encodeURIComponent(id)}`);
    const runLink = (id, label = `Run #${id}`) => {
        const node = anchor(label, `/workflow/runs/${id}`);
        node.addEventListener('click', (event) => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            openRun(id);
        });
        return node;
    };
    const dot = (label, tone, className = 'control-dot') => {
        const node = el('span', label, className);
        node.dataset.tone = tone;
        return node;
    };
    const names = {
        queued: '排队中', retry: '等待重试', claimed: '执行中', unknown: '状态不确定',
        done: '本轮已结束', nothing: '无事可做', cancelled: '已取消', failed: '执行失败',
        approval: '待确认外发', approved: '等待派发', running: '执行中', decision: '待你决定',
        draft: '待验收', accepted: '已验收',
    };
    const stateName = (state) => names[state] || state || '未记录';
    const runState = (run) => run.state === 'queued' && run.attempts > 0 ? 'retry' : run.state;
    const active = (run) => ['queued', 'claimed', 'unknown'].includes(run.state);
    const tone = (state) => ({ claimed: 'blue', unknown: 'orange', retry: 'orange', done: 'green', accepted: 'green' })[state] || 'gray';
    const runStatus = (run) => run.stopping ? '正在停止'
        : runState(run) === 'retry' ? `等待重试 · 第 ${run.attempts} 次失败` : stateName(run.state);
    const overview = [
        ['running', '运行中'], ['queue', '排队 / 重试'], ['ask', '待人工决策'],
        ['today', '今日完成'], ['unknown', '状态不确定'],
    ];
    const stages = [
        ['sources', '事件来源', 'Event Source', '已配置的事件来源'],
        ['event', '接收事件', 'Ingestion', '中台记下的事件'],
        ['normalize', '清洗与去重', 'Deduplication', '上游无独立 Fact'],
        ['rule', '规则匹配', 'Rule Matching', '派发关联的规则版本'],
        ['matter', '事项归并', 'Matter / Lane', '运行所属的组与 Lane'],
        ['queue', '队列', 'Queue', '等待派发和重试'],
        ['claim', 'Worker 领取', 'Worker Claim', '领取事实与接单程序'],
        ['context', '准备上下文', 'Context', '历史未记录独立事件'],
        ['start', 'Agent 执行', 'Agent Execution', '开始、运行与不确定状态'],
        ['receipt', '提交回执', 'Receipt Submission', '上游记录的执行结果'],
        ['parse', '解析回执', 'Receipt Parsing', '与回执同一事务'],
        ['actions', '后续动作', 'Follow-up', '由卡片、计时器和事件证明'],
    ];
    const branches = [
        ['ask', 'ASK', '人工决策'], ['notice', 'NOTICE', '通知'],
        ['later', 'LATER', '定时复查'], ['emit', 'EVENTS', '发出事件'], ['results', '结果', 'Done / Nothing / Cancelled'],
    ];
    const stageKinds = { sources: ['event'], normalize: ['event'], context: ['claim', 'start'],
        parse: ['receipt'], actions: ['card', 'later', 'emit', 'followup'] };
    const stageStatus = { idle: ['空闲', 'gray'], pending: ['等待处理', 'orange'], processing: ['处理中', 'blue'],
        completed: ['已观测', 'green'], warning: ['待关注', 'orange'], failed: ['有失败记录', 'red'],
        unknown: ['状态未知', 'gray'], unobserved: ['不可单独观测', 'gray'] };
    let state, connection = 'connecting', stream, received = 0, applied = 0, refreshing, refreshTimer, reconnect;
    let rerun = false, lastSync, extra = new Map(), cursor, loadingOlder = false, drawer = null;
    let matterFilter = '', drawerRequest = 0, cardDrawer = null;
    const dirtyRuns = new Map();
    const health = { connecting: ['正在连接', 'blue'], online: ['正常在线', 'green'],
        stale: ['暂时异常 · 数据已过期', 'orange'], offline: ['服务不可用', 'red'] };
    const day = (value) => value ? new Intl.DateTimeFormat('sv-SE', {
        timeZone: state?.timezone || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date(value)) : '';
    const time = (value) => value ? new Intl.DateTimeFormat('zh-CN', {
        timeZone: state?.timezone || 'UTC', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    }).format(new Date(value)) : '未记录';
    const usage = (value) => value ? [
        ['input', '输入'], ['output', '输出'], ['cached', '缓存'], ['cost', '成本'],
    ].filter(([key]) => Object.hasOwn(value, key)).map(([key, label]) =>
        `${label} ${key === 'cost' ? '$' : ''}${value[key]}`).join(' · ') : '未上报';
    const duration = (start, end) => {
        if (!start || !end) return '未记录';
        const seconds = Math.max(0, Math.floor((new Date(end) - new Date(start)) / 1000));
        return seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
    };
    const allRuns = () => [...new Map([...extra, ...(state?.runs || []).map((r) => [r.id, r])]).values()]
        .sort((a, b) => b.id - a.id);
    const agentName = (id) => state?.agents.find((agent) => agent.id === id)?.name || id || '未记录';
    const present = (entries) => {
        if (!entries?.length || !entries.some((entry) => entry.seenAt)) return ['状态未知', 'gray'];
        const online = entries.filter((entry) => entry.online).length;
        const known = entries.filter((entry) => entry.seenAt).length;
        return [`${online}/${entries.length} 在线${known < entries.length ? ' · 部分未知' : ''}`,
            online === entries.length ? 'green' : 'orange'];
    };
    const workerPresence = () => present([...new Map((state?.agents || [])
        .filter((agent) => agent.worker).map((agent) => [agent.worker, agent])).values()]);
    const empty = (text) => el('p', text, 'control-empty');
    const filters = $('history-filter').elements;
    const view = document.getElementById('workflow-control').dataset.view;
    const args = new URLSearchParams(location.search);
    const initialRun = /^\d+$/.test(args.get('run') || '') ? Number(args.get('run')) : null;
    let initialRule = args.get('rule');
    const initialCursor = /^\d+$/.test(args.get('before') || '') ? Number(args.get('before')) : null;

    function keyed(container, rows, key, draw, emptyText) {
        const previous = new Map([...container.children].map((node) => [node.dataset.key, node]));
        let index = 0;
        for (const row of rows) {
            const id = String(key(row));
            const hash = JSON.stringify(row);
            let node = previous.get(id);
            if (!node || (node.dataset.hash !== hash && !node.contains(document.activeElement))) {
                const next = draw(row);
                next.dataset.key = id;
                next.dataset.hash = hash;
                if (node) {
                    const open = node.querySelector('details[open]');
                    if (open && next.querySelector('details')) next.querySelector('details').open = true;
                    node.replaceWith(next);
                }
                node = next;
            }
            if (container.children[index] !== node && !node.contains(document.activeElement)) {
                container.insertBefore(node, container.children[index] || null);
            }
            previous.delete(id);
            index++;
        }
        for (const node of previous.values()) node.remove();
        if (!rows.length && emptyText) container.append(empty(emptyText));
    }

    function renderHealth() {
        const [label, color] = health[connection];
        const [worker, workerTone] = workerPresence();
        const [channels, channelTone] = present(state?.channels);
        const agent = state?.agents.length ? `${state.totals.running} 轮执行中 · ${state.agents.length} 个已配置` : '状态未知';
        $('health').replaceChildren(dot(`Autoloop ${label}`, color),
            dot(`Worker ${worker}`, workerTone), dot(`Agent ${agent}`, state?.agents.length ? 'blue' : 'gray'),
            dot(`通道 ${channels}`, channelTone));
        $('sync').textContent = lastSync ? `最后同步 ${time(lastSync)} · ${state.timezone} · 日志序号 ${applied}`
            : connection === 'offline' ? '未获得服务数据。可刷新重试，本地工作项仍可打开。' : '正在获取初始快照…';
    }

    function renderOverview() {
        const totals = state?.totals;
        const asks = state?.cards.filter((card) => card.kind === 'ask' && card.state === 'open').length;
        const counts = totals ? [totals.running, totals.queued, asks, totals.doneToday, totals.unknown] : [];
        keyed($('overview'), overview.map(([key, title], index) => ({
            key, title, value: counts[index], pressed: matterFilter === key || key === 'ask' && $('inbox-filter').value === 'ask',
        })), (row) => row.key, ({ key, title, value, pressed }) => {
            const node = button('', () => {
                if (key === 'ask') {
                    $('inbox-filter').value = $('inbox-filter').value === 'ask' ? 'open' : 'ask';
                    $('inbox').scrollIntoView({ block: 'start' });
                } else {
                    matterFilter = matterFilter === key ? '' : key;
                    if (matterFilter && view === 'overview') $('matters').scrollIntoView({ block: 'start' });
                }
                render();
            });
            node.setAttribute('aria-pressed', pressed);
            node.append(el('strong', value ?? '—'), el('span', title));
            if (key === 'today') {
                node.title = '按规则时区统计，采用上游今日 done 汇总；不包含取消和无事可做';
                node.append(el('small', '规则时区 · 仅 done'));
            }
            return node;
        });
        for (const node of $('overview').children) {
            node.setAttribute('aria-pressed', node.dataset.key === 'ask' ? $('inbox-filter').value === 'ask' : matterFilter === node.dataset.key);
        }
    }

    function observations(id) {
        const kinds = stageKinds[id] || (id === 'results' ? ['receipt', 'stop']
            : ['ask', 'notice'].includes(id) ? ['card'] : [id]);
        const found = new Map();
        for (const step of state?.activity || []) {
            if (!kinds.includes(step.kind)) continue;
            if (['ask', 'notice'].includes(id) && step.cardKind !== id) continue;
            if (id === 'results' && !['done', 'nothing', 'cancelled'].includes(step.outcome || step.state)) continue;
            const key = JSON.stringify([step.seq, step.kind, step.event ?? step.card ?? step.timer ?? step.runId]);
            if (!found.has(key)) found.set(key, step);
        }
        return [...found.values()];
    }

    function stageRow([id, name, english, description], index) {
        const records = observations(id);
        const latest = records[0];
        let amount = state ? records.length : null;
        let scope = '近期事实';
        let status = !state ? 'unknown' : records.length ? 'completed' : 'idle';
        if (['normalize', 'context', 'parse'].includes(id)) {
            status = 'unobserved';
            amount = null;
        } else if (state && id === 'sources') {
            amount = state.sources.length;
            scope = '已配置来源';
            status = latest ? 'completed' : 'idle';
        } else if (state && id === 'queue' && state.totals.queued) {
            amount = state.totals.queued;
            scope = '当前排队';
            status = 'pending';
        } else if (state && id === 'start') {
            const started = state.runs.filter((run) => run.state === 'claimed' && run.started != null).length;
            if (started) { amount = started; scope = '已开始的运行'; status = 'processing'; }
            else if (state.totals.unknown) { amount = state.totals.unknown; scope = '状态不确定'; status = 'unknown'; }
            else if (records.some((record) => state.runs.find((run) => run.id === record.runId)?.state === 'claimed')) {
                status = 'processing';
            }
        } else if (state && id === 'receipt' && latest?.outcome === 'failed') {
            status = 'failed';
        } else if (state && id === 'actions' && state.cards.some((card) => card.state === 'open')) {
            status = 'warning';
        }
        return { id, name, english, description, index: index + 1, latest, amount, scope, status };
    }

    function renderFlow() {
        keyed($('flow'), stages.map(stageRow), (row) => row.id, (row) => {
            const [status, color] = stageStatus[row.status];
            const node = button('', () => openStage(row.id, row.name), 'control-stage-btn');
            node.setAttribute('aria-haspopup', 'dialog');
            node.dataset.tone = color;
            node.title = [status, row.amount == null ? null : `${row.amount} ${row.scope}`,
                row.latest && `Fact #${row.latest.seq} · ${time(row.latest.at)}`].filter(Boolean).join(' · ');
            const heading = el('span', null, 'control-stage-name');
            heading.append(el('span', String(row.index).padStart(2, '0')), el('strong', row.name));
            const summary = row.latest?.summary || (row.latest && timelineLabels[row.latest.kind]);
            node.append(heading, el('small', row.english, 'control-stage-key'), el('small', row.description),
                dot(status, color, 'control-dot control-status'),
                el('small', row.amount == null ? '数量未单独记录' : `${row.amount} ${row.scope}`, 'control-stage-count'),
                el('small', row.latest ? `${time(row.latest.at)} · ${summary}` : '最近事实未记录', 'control-stage-last'));
            return node;
        });
        keyed($('branches'), branches.map(([id, title, label]) => {
            let count = state ? observations(id).length : null;
            let scope = '近期事实';
            if (state && id === 'ask') { count = state.cards.filter((c) => c.kind === 'ask' && c.state === 'open').length; scope = '待回答'; }
            if (state && id === 'notice') { count = state.cards.filter((c) => c.kind === 'notice').length; scope = '当前及近期通知'; }
            if (state && id === 'later') { count = state.timers.length; scope = '当前定时器'; }
            const results = state && id === 'results' ? ['done', 'nothing', 'cancelled'].map(
                (status) => state.runs.filter((run) => run.state === status).length,
            ) : null;
            return { id, title, label, count, scope, results };
        }), (row) => row.id, (row) => {
            const node = button('', () => openStage(row.id, row.label));
            node.setAttribute('aria-haspopup', 'dialog');
            node.append(el('strong', row.title), el('small', row.count == null ? '未同步' : `${row.count} ${row.scope}`));
            if (row.results) node.append(el('small', `已加载：完成 ${row.results[0]} · 无事 ${row.results[1]} · 取消 ${row.results[2]}`));
            return node;
        });
    }

    function factLink(step) {
        const row = el('article', null, 'control-row');
        const head = el('div', null, 'control-row-title');
        head.append(el('strong', timelineLabels[step.kind] || step.kind), el('small', `Fact #${step.seq} · ${time(step.at)}`));
        row.append(head);
        if (step.summary || step.title || step.type) row.append(el('p', step.summary || step.title || step.type));
        if (step.runId) row.append(runLink(step.runId));
        const json = el('details');
        json.append(el('summary', '事实字段（已脱敏）'), el('pre', JSON.stringify(step, null, 2)));
        row.append(json);
        return row;
    }

    function openStage(id, title) {
        cardDrawer = null;
        drawer = null;
        drawerRequest++;
        showDrawer(title);
        const body = $('drawer-body');
        body.replaceChildren();
        if (!state) { body.append(empty('暂未获得服务数据。')); return; }
        const records = observations(id);
        if (['normalize', 'context', 'parse'].includes(id)) {
            body.append(el('p', '不可单独观测。以下是可取得的上下游事实。', 'control-notice'));
        }
        if (id === 'sources') for (const source of state.sources) {
            body.append(el('p', `${source.name} · ${source.id} · ${source.events} 个事件`));
        }
        if (id === 'rule') for (const rule of state.lines) {
            body.append(el('p', `${rule.name} · ${trigger(rule)} · ${rule.paused ? '已暂停' : '已启用'}`));
        }
        if (['sources', 'event'].includes(id)) for (const event of state.unrouted) {
            const details = el('details');
            details.append(el('summary', `未路由 · Event #${event.id} · ${event.source} / ${event.type} · ${time(event.received_at)}`),
                el('pre', JSON.stringify(event, null, 2)));
            body.append(details);
        }
        if (id === 'later') for (const timer of state.timers) {
            body.append(el('p', `${timer.rule} · ${timer.key} · ${time(timer.at)}`));
        }
        const ids = new Set(records.map((step) => step.runId));
        const related = allRuns().filter((run) => ids.has(run.id) || (id === 'queue' && run.state === 'queued'));
        for (const run of related.slice(0, 8)) {
            const row = el('div', null, 'control-inline');
            row.append(runLink(run.id, `#${run.id} · ${runStatus(run)}`), matterLink(run, run.title));
            body.append(row);
        }
        if (['ask', 'notice', 'actions'].includes(id)) {
            const cards = state.cards.filter((card) => id === 'notice' ? card.kind === 'notice' : card.state === 'open' && (id === 'actions' || card.kind === id));
            for (const card of cards.slice(0, 8)) body.append(button(card.title, () => openCardContext(card), 'control-link'));
        }
        body.append(el('h3', '近期事实'));
        for (const step of records.slice(0, 12)) body.append(factLink(step));
        if (!records.length) body.append(empty('没有可展示的相关事实。'));
    }

    function runMatches(run) {
        return !matterFilter || matterFilter === 'running' && run.state === 'claimed'
            || matterFilter === 'queue' && run.state === 'queued'
            || matterFilter === 'unknown' && run.state === 'unknown'
            || matterFilter === 'today' && run.state === 'done' && day(run.finishedAt) === day(state.now);
    }

    function matters() {
        const groups = new Map();
        for (const item of state.items) groups.set(JSON.stringify(['local', item.id]), { item, runs: [], title: item.title });
        for (const run of allRuns()) {
            const key = JSON.stringify(run.matter);
            if (!groups.has(key)) groups.set(key, { runs: [], title: run.title });
            const group = groups.get(key);
            if (!group.item && !group.label && run.label) {
                group.title = run.label;
                group.label = true;
            }
            group.runs.push(run);
        }
        return [...groups].map(([key, group]) => ({ key, ...group })).filter((group) =>
            !matterFilter || group.runs.some(runMatches)).sort((a, b) => {
            const rank = (group) => group.runs.some(active) ? 2 : group.item && !group.runs.length ? 1 : 0;
            return rank(b) - rank(a) || (b.runs[0]?.id || 0) - (a.runs[0]?.id || 0);
        });
    }

    function runMeta(run) {
        return [run.rule, run.sources.join('、'), agentName(run.agent), run.worker ? `Worker ${run.worker}` : 'Worker 未记录',
            run.started ? `开始 ${time(run.started)}` : run.claimedAt ? `领取 ${time(run.claimedAt)}` : `排队 ${time(run.createdAt)}`,
            `失败 ${run.attempts ?? '未记录'} 次`, `${run.cards.length} 张已关联卡片`].filter(Boolean).join(' · ');
    }

    function renderMatters() {
        const filter = overview.find(([key]) => key === matterFilter)?.[1];
        $('clear').hidden = !filter;
        $('matter-filter').hidden = !filter;
        $('matter-filter').textContent = filter ? `筛选：${filter} · 仅已加载轮次` : '';
        keyed($('matters-list'), matters(), (group) => group.key, (group) => {
            const node = el('article', null, 'control-row');
            const head = el('div', null, 'control-row-title');
            const relevant = group.runs.find((run) => active(run) && runMatches(run)) || group.runs.find(runMatches);
            const title = group.runs.length ? matterLink(relevant || group.runs[0], group.title)
                : button(group.title, () => openLocal(group.item), 'control-link');
            head.append(title);
            if (group.item) {
                const local = group.item.state === 'failed' ? '待重新确认' : group.item.state ? stateName(group.item.state) : '待填写目标';
                head.append(dot(local, tone(group.item.state)));
            } else if (relevant) {
                const review = state.timers.some((timer) => timer.rule === relevant.rule && timer.lane === relevant.lane);
                head.append(dot(active(relevant) ? runStatus(relevant) : review ? '等待复查' : '查看回执与后续', tone(runState(relevant))));
            }
            node.append(head);
            if (relevant) {
                const row = el('div', null, 'control-rows-sub');
                row.append(runLink(relevant.id, `Run #${relevant.id} · ${runStatus(relevant)}`), el('small', runMeta(relevant)));
                if (group.runs.length > 1) row.append(matterLink(relevant, `查看已加载的 ${group.runs.length} 轮`));
                if (group.item) row.append(itemLink(group.item.id));
                node.append(row);
            }
            return node;
        }, filter ? '当前已加载轮次没有匹配记录。' : '还没有事项。可以从日常工作的任务菜单交给 AI，或在这里新建。');
    }

    function feedback(text, error = false) {
        $('feedback').hidden = !text;
        $('feedback').textContent = text;
        $('feedback').dataset.tone = error ? 'red' : 'blue';
    }

    async function api(path, options = {}) {
        const response = await fetch(path, { cache: 'no-store', ...options });
        let data;
        try { data = await response.json(); } catch { /* No JSON on transport failure. */ }
        if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `请求未完成（${response.status}）`);
        return data;
    }

    async function action(node, path, body, message, success, live = null) {
        if (!window.confirm(message)) return;
        node.disabled = true;
        if (live) live.textContent = '正在提交…';
        try {
            await api(path, {
                method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body),
                headers: { Accept: 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content,
                    ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }) },
            });
            feedback(success);
            if (live) live.textContent = success;
            await refresh();
        } catch (error) {
            feedback(error.message, true);
            if (live) live.textContent = error.message;
        } finally {
            node.disabled = false;
            if (node.isConnected && node.dataset.locked === 'true') node.disabled = true;
        }
    }

    function cardAction(node, card) {
        const ask = card.kind === 'ask';
        const form = el('form', null, 'control-card-form');
        const select = el('select');
        const text = el('textarea');
        text.rows = 2;
        text.maxLength = 4000;
        if (ask && card.options.length) {
            const label = el('label', '预设选项');
            const placeholder = el('option', '请选择（或填写文字）');
            placeholder.value = '';
            select.append(placeholder);
            for (const [i, name] of card.options.entries()) {
                const option = el('option', name);
                option.value = i;
                select.append(option);
            }
            label.append(select);
            form.append(label);
        }
        const label = el('label', ask ? '自由文本回答' : '处理原因');
        text.required = !ask;
        label.append(text);
        const submit = el('button', ask ? '确认回答' : '结案');
        const live = el('small');
        live.setAttribute('role', 'status');
        form.append(label, submit, live);
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            const value = text.value.trim();
            const choice = select.value;
            if (ask && Boolean(value) === Boolean(choice) || !ask && !value) {
                live.textContent = ask ? '请选择一个选项或填写文字。' : '请填写处理原因。';
                return;
            }
            const path = `/workflow/cards/${card.id}/${ask ? 'answer' : 'resolve'}`;
            action(submit, path, ask ? value ? { text: value } : { choice: Number(choice) } : { reason: value },
                ask ? '确认提交这次回答？' : '确认以填写的原因结案？',
                ask ? '已回答 · 等待续跑' : '通知已结案', live);
        });
        node.append(form);
    }

    function renderCards() {
        const mode = $('inbox-filter').value;
        const cards = state.cards.filter((card) => mode === 'recent' ? card.state !== 'open'
            : card.state === 'open' && (mode !== 'ask' || card.kind === 'ask'));
        if (mode === 'open') cards.sort((a, b) => Number(b.kind === 'ask') - Number(a.kind === 'ask'));
        keyed($('cards'), cards, (card) => card.id, (card) => {
            const node = el('article', null, 'control-row');
            const open = card.state === 'open';
            const ask = card.kind === 'ask';
            const status = open ? '等待处理' : card.state === 'decided'
                ? card.following.length ? '已回答 · 已关联续跑' : '已回答 · 等待续跑'
                : card.state === 'done' ? '续跑已回执' : card.fyi ? '仅告知' : card.fyi == null && !ask ? '已关闭 · 类型未上报' : '已结案';
            const head = el('div', null, 'control-row-title');
            head.append(el('h3', card.title), dot(`${ask ? 'ASK' : 'NOTICE'} · ${status}`, open ? 'orange' : 'gray'));
            node.append(head, el('p', card.text, 'control-card-text'));
            const meta = el('small', `${card.rule || '未记录规则'} · 创建于 ${time(card.createdAt)}`);
            if (open && card.createdAt) {
                const age = el('span');
                age.dataset.waiting = card.createdAt;
                meta.append(age);
            }
            node.append(meta);
            if (ask && card.options[card.recommend]) {
                node.append(el('small', `推荐：${card.options[card.recommend]} · 推荐理由未上报`));
            }
            if (!open && (card.answer || card.options[card.choice] || card.result)) {
                node.append(el('p', card.answer || card.options[card.choice] || card.result));
            }
            const links = el('div', null, 'control-inline');
            if (card.item) links.append(itemLink(card.item, open ? '查看工作项并预览确认' : '查看工作项'));
            if (card.run) links.append(runLink(card.run, `查看关联事项与 Run #${card.run}`));
            for (const id of card.following) links.append(runLink(id, `续跑 #${id}`));
            if (links.children.length) node.append(links);
            else if (!card.run) node.append(el('small', '上游未提供可验证的原始轮次。'));
            node.append(button('查看决策上下文', () => openCardContext(card), 'control-link'));
            return node;
        }, mode === 'recent' ? '暂无近期处理过的卡片。' : '没有待处理卡片。');
        updateWaiting();
    }

    function updateWaiting() {
        for (const node of $('cards').querySelectorAll('[data-waiting]')) {
            const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(node.dataset.waiting)) / 60000));
            node.textContent = minutes < 1 ? ' · 刚刚创建' : minutes < 60 ? ` · 已等待 ${minutes} 分钟` : ` · 已等待 ${Math.floor(minutes / 60)} 小时`;
        }
    }

    function trigger(rule) {
        return rule.every ? `定时 · ${rule.every}` : `事件 · ${(rule.types || []).join('、') || '未列出类型'}`;
    }

    function renderRules() {
        const runs = allRuns();
        keyed($('rules-list'), state.lines.map((rule) => ({
            ...rule, recent: runs.find((run) => run.rule === rule.name),
        })), (rule) => rule.name, (rule) => {
            const node = el('article', null, 'control-row');
            const head = el('div', null, 'control-row-title');
            head.append(el('h3', rule.name), dot(rule.paused ? '已暂停' : '已启用', rule.paused ? 'orange' : 'green'));
            node.append(head, el('small', [trigger(rule), `来源 ${rule.source || '未记录'}`, `Agent ${agentName(rule.agent)}`,
                `Worker ${rule.worker || '未记录'}`, `CWD ${rule.file?.cwd || '未记录'}`].join(' · ')));
            if (rule.recent) node.append(runLink(rule.recent.id, `最近已加载轮次 #${rule.recent.id} · ${runStatus(rule.recent)} · ${time(rule.recent.finishedAt || rule.recent.started || rule.recent.createdAt)}`));
            else node.append(el('small', '已加载历史中没有执行记录。'));
            const operations = el('div', null, 'control-inline');
            for (const [op, title] of [['run', '立即运行'], rule.paused ? ['resume', '恢复规则'] : ['pause', '暂停规则']]) {
                const cmd = button(title, () => {
                    const form = new FormData();
                    form.set('name', rule.name);
                    action(cmd, `/workflow/rules/${op}`, form, `确认${title}「${rule.name}」？`, `${title}请求已获 Autoloop 确认`);
                });
                cmd.disabled = op === 'run' && rule.paused;
                operations.append(cmd);
            }
            operations.append(button('查看执行历史', () => {
                location.assign(`/tasks/history?rule=${encodeURIComponent(rule.name)}`);
            }, 'control-link'));
            const config = el('details');
            config.append(el('summary', '查看配置'));
            config.append(el('p', '运行中：' + [trigger(rule), rule.source, rule.group ? `组 ${rule.group}` : null,
                rule.next ? `下次检查 ${time(rule.next)}` : null].filter(Boolean).join(' · ')));
            config.append(el('small', '下方是本机 rules.json 的只读摘要，文件改动只有通过上游校验后才会生效。校验命令：agent-autoloop check。'));
            if (rule.file) config.append(el('pre', JSON.stringify(rule.file, null, 2)));
            else config.append(el('p', '未读取到同名的本地规则文件。'));
            node.append(operations, config);
            return node;
        }, '没有已配置的规则。');
    }

    function fillOptions(select, items) {
        const hash = JSON.stringify(items);
        if (select.dataset.hash === hash) return;
        const prior = select.value;
        select.replaceChildren();
        for (const [id, name] of [['', '全部'], ...items]) {
            const option = el('option', name);
            option.value = id;
            select.append(option);
        }
        select.value = items.some(([id]) => id === prior) ? prior : '';
        select.dataset.hash = hash;
    }

    function renderHistory() {
        const runs = allRuns();
        const titles = new Map();
        for (const run of runs) if (run.label) {
            const key = JSON.stringify(run.matter);
            if (!titles.has(key)) titles.set(key, run.label);
        }
        const title = (run) => titles.get(JSON.stringify(run.matter)) || run.title;
        fillOptions(filters.rule, [...new Set([...state.lines.map((rule) => rule.name), ...runs.map((run) => run.rule)])].sort().map((name) => [name, name]));
        if (initialRule && [...filters.rule.options].some((option) => option.value === initialRule)) {
            filters.rule.value = initialRule;
            initialRule = null;
        }
        fillOptions(filters.agent, [...new Set([...state.agents.map((agent) => agent.id), ...runs.map((run) => run.agent)])].sort().map((id) => [id, agentName(id)]));
        fillOptions(filters.status, ['queued', 'retry', 'claimed', 'unknown', 'done', 'nothing', 'cancelled'].map((key) => [key, stateName(key)]));
        const query = filters.search.value.trim().toLowerCase();
        const rows = runs.filter((run) => {
            const date = day(run.started || run.claimedAt || run.createdAt);
            return (!filters.rule.value || filters.rule.value === run.rule) && (!filters.agent.value || filters.agent.value === run.agent)
                && (!filters.status.value || filters.status.value === runState(run))
                && (!filters.from.value || filters.from.value <= date) && (!filters.to.value || date <= filters.to.value)
                && (!query || `Run #${run.id} ${title(run)}`.toLowerCase().includes(query));
        });
        keyed($('history-list'), rows.map((run) => ({ ...run, displayTitle: title(run) })), (run) => run.id, (run) => {
            const row = el('tr');
            const id = el('td');
            id.append(runLink(run.id), el('small', run.displayTitle));
            const rule = el('td');
            rule.append(el('span', run.rule), el('small', agentName(run.agent)));
            const status = el('td');
            status.append(dot(runStatus(run), tone(runState(run))));
            if (run.summary || run.error) status.append(el('small', run.error || run.summary));
            const dates = el('td');
            dates.append(el('span', time(run.started)), el('small', time(run.finishedAt)));
            row.append(id, rule, status, dates, el('td', duration(run.started, run.finishedAt)),
                el('td', run.attempts ?? '未记录'), el('td', usage(run.usage)));
            return row;
        });
        $('history-empty').hidden = rows.length > 0;
        $('history-empty').textContent = '已加载记录中没有匹配的轮次。';
        $('history-scope').textContent = `已加载 ${runs.length} 轮 · 显示 ${rows.length} 轮 · 日期按 ${state.timezone}`;
        $('more').hidden = !cursor;
        $('more').disabled = loadingOlder;
    }

    const timelineLabels = {
        event: '事件接入', rule: '规则匹配', matter: '事项归并', queue: '进入队列', claim: 'Worker 领取', start: 'Agent 开始执行',
        receipt: '提交回执', emit: 'Events · 发出事件', later: 'Later · 定时复查', card: '生成卡片',
        answer: '人工回答', card_closed: '卡片处理结果', followup: '关联续跑', stop: '停止请求', unknown: '状态不确定',
    };

    function drawStep(step) {
        const node = el('li');
        node.dataset.tone = ['card', 'answer', 'card_closed', 'followup'].includes(step.kind) ? 'orange'
            : ['claim', 'start', 'receipt'].includes(step.kind) ? 'blue' : 'gray';
        node.append(el('strong', timelineLabels[step.kind]), el('small', `${time(step.at)} · #${step.seq}`, 'control-run-meta'));
        const info = {
            event: [step.source, step.type, step.subject, step.summary, step.received_at && `接收 ${time(step.received_at)}`],
            rule: [step.rule, step.version && `配置版本 #${step.version}`, step.config?.cwd && `CWD ${step.config.cwd}`],
            matter: [step.group && `组 ${step.group}`, step.lane ? `lane ${step.lane}` : '默认 lane'],
            claim: [step.worker || 'Worker 未记录', step.agent && agentName(step.agent)],
            start: [agentName(step.agent), step.session && `Session ${step.session}`],
            receipt: [stateName(step.outcome), step.summary || step.error, usage(step.usage),
                step.outcome === 'failed' && step.not_before ? `不早于 ${time(step.not_before)} 重试` : null],
            emit: [step.source, step.type, step.subject, step.summary],
            later: [step.key, step.due && time(step.due), step.about, step.cancelled && '取消定时复查'],
            card: [step.cardKind?.toUpperCase(), step.card && `#${step.card}`, step.title, step.text],
            answer: [step.card && `#${step.card}`, step.selected || (step.choice != null ? `选项 ${step.choice + 1}` : ''), step.answer, step.by],
            card_closed: [step.card && `#${step.card}`, step.result],
            followup: [step.card && `来自卡片 #${step.card}`],
            stop: [stateName(step.state)],
            unknown: [step.error || '未收到可确认的结果'],
        }[step.kind];
        if (info) node.append(el('p', info.filter(Boolean).join(' · '), 'control-card-text'));
        if (step.link) node.append(anchor('打开原始会话 ↗', step.link));
        if (step.kind === 'followup') node.append(runLink(step.run));
        const details = el('details');
        details.append(el('summary', '事实字段（已脱敏）'), el('pre', JSON.stringify(step, null, 2)));
        node.append(details);
        return node;
    }

    function showDrawer(title) {
        $('drawer-title').textContent = title;
        if (!$('drawer').open) {
            $('drawer').showModal();
            $('drawer-title').focus();
        }
    }

    function matterLink(run, title) {
        const query = run.item ? `item=${encodeURIComponent(run.item)}` : `run=${run.id}`;
        const node = anchor(title, `/tasks/matters?${query}`);
        node.addEventListener('click', (event) => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            openMatter(query);
        });
        return node;
    }

    function openLocal(item) {
        openMatter(`item=${encodeURIComponent(item.id)}`);
    }

    async function openMatter(query, inline = false) {
        cardDrawer = null;
        const request = ++drawerRequest;
        drawer = null;
        const body = inline ? $('matter-page') : $('drawer-body');
        if (!inline) showDrawer('事项详情');
        body.replaceChildren(el('p', '正在读取事项…'));
        try {
            const data = await api(`/workflow/control/matter?${query}`);
            if (request !== drawerRequest) return;
            if (!inline) showDrawer(data.title || '事项详情');
            drawMatter(body, data, query, inline);
        } catch (error) {
            if (request === drawerRequest) body.replaceChildren(el('p', error.message),
                button('重试', () => openMatter(query, inline)));
        }
    }

    function drawMatter(body, matter, query, inline) {
        const title = el('h2', matter.title);
        const runs = matter.runs;
        const rules = [...new Set(runs.map((run) => run.rule).filter(Boolean))];
        const overview = el('div', null, 'control-detail-stack');
        const first = runs.map((run) => run.createdAt).filter(Boolean).sort()[0];
        const latest = matter.history[0]?.at || runs[0]?.finishedAt;
        const summary = [
            matter.item ? `工作台事项 ${matter.item}` : `组 ${matter.identity[0] || '未上报'} · Lane ${matter.identity[1] || '默认'}`,
            `规则 ${rules.join('、') || '未上报'}`,
            `状态 ${matter.localState ? stateName(matter.localState) : '查看各轮执行状态'}`,
            `最早记录 ${time(first)} · 最近活动 ${time(latest)}`,
            `${runs.length} 轮已关联${matter.more ? ' · 可加载更早记录' : ''}`,
        ];
        overview.append(...summary.map((line) => el('p', line)));
        if (matter.item) overview.append(itemLink(matter.item));
        if (!inline) overview.append(anchor('在独立页面打开', `/tasks/matters?${query}`));

        const runList = el('div', null, 'control-list');
        for (const run of runs) {
            const row = el('article', null, 'control-row');
            row.append(runLink(run.id), el('small', [
                run.state ? runStatus(run) : '上游状态未加载',
                run.localState ? `工作项 ${stateName(run.localState)}` : null, run.rule, run.agent,
                time(run.started ?? run.createdAt),
            ].filter(Boolean).join(' · ')));
            runList.append(row);
        }
        if (!runs.length) runList.append(empty('尚无已关联运行。'));

        const cardList = el('div', null, 'control-list');
        for (const card of matter.cards) {
            const full = state?.cards.find((candidate) => candidate.id === card.id)
                || (card.text ? { ...card, run: card.run ?? card.run_id, item: card.item ?? matter.item } : null);
            const row = el('article', null, 'control-row');
            row.append(el('strong', `${card.kind.toUpperCase()} · ${card.title}`), el('small', card.state));
            if (full) row.append(button('查看决策上下文', () => openCardContext(full), 'control-link'));
            const source = card.run ?? card.run_id;
            if (source) row.append(runLink(source, `来源 #${source}`));
            for (const next of card.following || []) row.append(runLink(next, `续跑 #${next}`));
            cardList.append(row);
        }
        if (!matter.cards.length) cardList.append(empty('未找到相关卡片。'));
        const timerList = el('div', null, 'control-detail-stack');
        for (const timer of matter.timers) timerList.append(el('p', `${timer.rule} · ${timer.key} · ${time(timer.at)}`));
        if (!matter.timers.length) timerList.append(empty('没有已关联的待触发定时器。'));
        const historyList = (eventsOnly) => {
            const panel = el('div', null, 'control-list');
            const rows = eventsOnly ? matter.history.filter((step) => ['event', 'emit'].includes(step.kind)) : matter.history;
            if (matter.historyUnavailable.length) panel.append(el('p',
                `暂时读不到这些轮次的日志：${matter.historyUnavailable.map((id) => `#${id}`).join('、')}`, 'control-notice'));
            panel.append(...rows.map(factLink));
            if (!rows.length) panel.append(empty('该范围没有可用事实。可从关联轮次检查其完整日志。'));
            return panel;
        };
        const tabbar = el('nav', null, 'control-inline control-tabs');
        tabbar.setAttribute('aria-label', '事项详情视图');
        const panel = el('div', null, 'control-detail-stack');
        const tabs = [['概览', () => overview], ['执行轮次', () => runList], ['决策卡片', () => cardList],
            ['定时器', () => timerList], ['原始事件', () => historyList(true)], ['完整历史', () => historyList(false)]];
        tabs.forEach(([label, draw], index) => {
            const tab = button(label, () => {
                for (const sibling of tabbar.children) sibling.setAttribute('aria-pressed', sibling === tab);
                panel.replaceChildren(draw());
            });
            tab.setAttribute('aria-pressed', index === 0);
            tabbar.append(tab);
        });
        panel.append(overview);
        body.replaceChildren(title, tabbar, panel);
        if (matter.nextBefore) {
            const load = button('加载更早的关联记录', async () => {
                load.disabled = true;
                try {
                    const older = await api(`/workflow/control/matter?${query}&before=${matter.nextBefore}`);
                    const merge = (current, rows, key) => [...new Map([...rows, ...current].map((row) => [key(row), row])).values()];
                    matter.runs = merge(matter.runs, older.runs, (row) => row.id).sort((a, b) => b.id - a.id);
                    matter.cards = merge(matter.cards, older.cards, (row) => row.id);
                    matter.history = merge(matter.history, older.history, (row) => `${row.seq}:${row.runId}:${row.kind}:${row.event ?? row.card ?? ''}`)
                        .sort((a, b) => b.seq - a.seq);
                    matter.historyUnavailable = [...new Set([...matter.historyUnavailable, ...older.historyUnavailable])];
                    matter.nextBefore = older.nextBefore;
                    matter.more = older.more;
                    drawMatter(body, matter, query, inline);
                } catch (error) {
                    load.disabled = false;
                    feedback(error.message, true);
                }
            });
            body.append(load);
        }
    }

    async function openCardContext(card, update = false) {
        const request = ++drawerRequest;
        drawer = null;
        cardDrawer = card.id;
        if (!update) showDrawer(card.title);
        const body = $('drawer-body');
        const open = card.state === 'open';
        const ask = card.kind === 'ask';
        body.replaceChildren(el('p', card.text, 'control-card-text'), el('small', [
            `${ask ? 'ASK' : 'NOTICE'} #${card.id}`, card.fyi ? '仅告知' : open ? '等待处理' : '已处理',
            card.rule, `创建 ${time(card.createdAt)}`, card.decidedAt && `回答 ${time(card.decidedAt)}`,
            card.closedAt && `关闭 ${time(card.closedAt)}`,
        ].filter(Boolean).join(' · ')));
        if (card.answer || card.options?.[card.choice] || card.result) {
            body.append(el('p', card.answer || card.options[card.choice] || card.result, 'control-card-text'));
        }
        if (card.options?.[card.recommend]) body.append(el('p', `推荐选项：${card.options[card.recommend]}`));
        if (card.item) body.append(itemLink(card.item, open ? '打开工作项，预览并确认' : '打开工作项'));
        if (card.run) {
            const run = allRuns().find((row) => row.id === card.run);
            if (run) body.append(matterLink(run, '查看所属事项'));
            body.append(runLink(card.run, `查看原轮次 #${card.run}`));
        }
        for (const id of card.following) body.append(runLink(id, `已关联续跑 #${id}`));
        if (ask && !open && !card.following.length) body.append(empty('尚未取得后续轮次事实。'));
        if (open && !card.item && !card.fyi) cardAction(body, card);
        if (!card.run) return;
        try {
            const data = await api(`/workflow/control/runs/${card.run}`);
            if (request !== drawerRequest) return;
            if (data.agent) body.prepend(el('small', `Agent ${agentName(data.agent)} · Worker ${data.worker || '未上报'}`));
            const receipt = data.timeline.filter((step) => step.kind === 'receipt').at(-1);
            body.append(receipt ? factLink(receipt) : empty('来源轮次没有可用的回执事实。'));
            for (const id of data.nativeFollowing || []) {
                if (!card.following.includes(id)) body.append(runLink(id, `轮次关联 #${id}`));
            }
        } catch {
            if (request === drawerRequest) body.append(empty('暂时无法读取来源轮次。'));
        }
    }

    async function openRun(id, live = false) {
        cardDrawer = null;
        const request = ++drawerRequest;
        drawer = id;
        const run = allRuns().find((row) => row.id === id);
        const body = $('drawer-body');
        if (!live) {
            showDrawer((run && matters().find((group) => group.runs.some((entry) => entry.id === id))?.title) || run?.title || `运行 #${id}`);
            body.replaceChildren(el('p', '正在读取本轮事实…'));
            $('drawer').scrollTop = 0;
        }
        try {
            const data = await api(`/workflow/control/runs/${id}`);
            if (request !== drawerRequest || !$('drawer').open) return;
            const neighbors = run ? allRuns().filter((entry) => JSON.stringify(entry.matter) === JSON.stringify(run.matter)) : [];
            const hash = JSON.stringify([data, run, neighbors.map((row) => row.id)]);
            if (live && body.dataset.hash === hash) return;
            body.dataset.hash = hash;
            const top = el('div', null, 'control-row-title');
            top.append(dot(`#${id} · ${runStatus({ ...data })}`, tone(runState(data))));
            if (data.item || run?.item) top.append(itemLink(data.item || run.item));
            const summary = el('small', [data.rule, data.group && `组 ${data.group}`, data.lane ? `lane ${data.lane}` : null,
                agentName(data.agent), data.worker && `Worker ${data.worker}`, `失败 ${data.attempts ?? '未记录'} 次`,
                `耗时 ${duration(data.started, data.finishedAt)}`, usage(data.usage)].filter(Boolean).join(' · '));
            const related = el('div', null, 'control-inline');
            related.append(anchor('完整时间线与回放', `/workflow/runs/${id}`), anchor('查看 Agent 执行', `/tasks/sessions/${id}`));
            related.append(matterLink(run || { id, item: data.item }, '查看所属事项'));
            for (const row of neighbors) if (row.id !== id) related.append(runLink(row.id, `切换至 #${row.id}`));
            if (data.previous && !neighbors.some((row) => row.id === data.previous)) related.append(runLink(data.previous, `上一轮 #${data.previous}`));
            for (const next of new Set([...data.following, ...(data.nativeFollowing || [])])) related.append(runLink(next, `工作台续跑 #${next}`));
            if (data.link) related.append(anchor('打开原始会话 ↗', data.link));
            if (['queued', 'claimed'].includes(data.state)) {
                const stop = button(data.stopping ? '正在停止' : '停止本轮', () =>
                    action(stop, `/workflow/runs/${id}/cancel`, new FormData(), `确认停止 Run #${id}？`, `已提交停止请求 · #${id}`, drawerFeedback));
                stop.disabled = data.stopping;
                related.append(stop);
            }
            const drawerFeedback = el('p');
            drawerFeedback.setAttribute('role', 'status');
            const timeline = el('ol', null, 'control-timeline');
            for (const step of data.timeline) timeline.append(drawStep(step));
            const missing = data.missing?.length ? el('p', `未找到的事实：${data.missing.join('、')}`, 'control-notice') : '';
            body.replaceChildren(top, summary, related, drawerFeedback, missing, el('h3', '本轮执行事实'),
                data.timeline.length ? timeline : empty('尚未找到本轮事实。'));
        } catch (error) {
            if (request !== drawerRequest) return;
            if (live) feedback(`时间线更新失败：${error.message}`, true);
            else body.replaceChildren(el('p', error.message), button('重试', () => openRun(id)));
        }
    }

    function renderActivity() {
        const facts = [...new Map([...(state.activity || [])].reverse().map((step) => [step.seq, step])).values()]
            .sort((a, b) => b.seq - a.seq).slice(0, 8);
        keyed($('activity'), facts, (step) => step.seq, factLink, '尚无近期可观测事实。');
    }

    function render() {
        renderHealth();
        renderOverview();
        renderFlow();
        if (!state) return;
        renderMatters();
        renderCards();
        renderActivity();
        renderRules();
        renderHistory();
    }

    function scheduleRefresh() {
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(() => refresh(), 140);
    }

    function subscribe(seq) {
        clearTimeout(reconnect);
        reconnect = undefined;
        stream?.close();
        if (!navigator.onLine) return;
        received = seq;
        const source = new EventSource(`/workflow/control/stream?after=${seq}`);
        stream = source;
        source.addEventListener('connected', () => {
            if (stream !== source) return;
            if (connection !== 'online') scheduleRefresh();
        });
        source.addEventListener('fact', (event) => {
            if (stream !== source) return;
            const next = Number(event.lastEventId);
            if (!Number.isSafeInteger(next) || next <= received) return;
            const info = JSON.parse(event.data);
            if (next !== received + 1) rerun = true;
            received = next;
            if (next <= applied) return;
            for (const id of info.runs) dirtyRuns.set(id, next);
            if (rerun || info.tables.length) scheduleRefresh();
        });
        const disconnected = () => {
            if (stream !== source) return;
            source.close();
            stream = undefined;
            connection = state ? 'stale' : 'offline';
            renderHealth();
            clearTimeout(reconnect);
            reconnect = setTimeout(() => { reconnect = undefined; subscribe(applied); }, 2500);
        };
        source.addEventListener('disconnected', disconnected);
        source.onerror = disconnected;
    }

    async function refresh(manual = false) {
        if (!navigator.onLine) return;
        if (refreshing) {
            rerun = true;
            return refreshing;
        }
        const refreshButton = $('refresh');
        refreshButton.disabled = true;
        if (manual && !state) { connection = 'connecting'; renderHealth(); }
        refreshing = (async () => {
            try {
                const next = await api('/workflow/control/state');
                if (state && next.seq < applied) {
                    extra = new Map();
                    cursor = undefined;
                    subscribe(next.seq);
                }
                if (!extra.size) cursor = next.nextBefore;
                const updateDrawer = drawer != null && (manual || (dirtyRuns.get(drawer) ?? Infinity) <= next.seq
                    || next.runs.some((row) => row.id === drawer && JSON.stringify(row) !== JSON.stringify(state?.runs.find((r) => r.id === drawer))));
                const activeCard = next.cards.find((card) => card.id === cardDrawer);
                const previousCard = state?.cards.find((card) => card.id === cardDrawer);
                const updateCard = activeCard && JSON.stringify(activeCard) !== JSON.stringify(previousCard);
                state = next;
                applied = next.seq;
                lastSync = next.now;
                connection = navigator.onLine ? 'online' : 'stale';
                if (!stream && navigator.onLine) subscribe(applied);
                render();
                if (updateDrawer) openRun(drawer, true);
                else if (updateCard && (!document.activeElement?.closest('.control-card-form') || activeCard.state !== previousCard?.state)) {
                    openCardContext(activeCard, true);
                }
                for (const [id, seq] of dirtyRuns) if (seq <= applied) dirtyRuns.delete(id);
                if (received > applied && stream) rerun = true;
            } catch (error) {
                connection = state ? 'stale' : 'offline';
                renderHealth();
                if (!state) for (const id of ['cards', 'rules-list']) $(id).replaceChildren(empty('服务暂不可用。'));
                if (!state) $('history-empty').textContent = '服务暂不可用。';
                if (manual) feedback(error.message, true);
                if (!stream && !reconnect) reconnect = setTimeout(() => { reconnect = undefined; refresh(); }, 2500);
            }
        })();
        await refreshing;
        refreshing = null;
        refreshButton.disabled = false;
        if (rerun) {
            rerun = false;
            scheduleRefresh();
        }
    }

    async function loadOlder(before = cursor) {
        if (!before || loadingOlder) return;
        loadingOlder = true;
        $('more').disabled = true;
        try {
            const page = await api(`/workflow/control/state?before=${before}`);
            for (const run of page.runs) extra.set(run.id, run);
            cursor = page.nextBefore;
            render();
        } catch (error) {
            feedback(error.message, true);
        } finally {
            loadingOlder = false;
            $('more').disabled = false;
        }
    }

    $('refresh').onclick = () => refresh(true);
    $('clear').onclick = () => { matterFilter = ''; render(); };
    $('inbox-filter').onchange = () => { if (state) renderCards(); renderOverview(); };
    $('history-filter').addEventListener('submit', (event) => event.preventDefault());
    $('history-filter').addEventListener('input', () => { if (state) renderHistory(); });
    $('more').onclick = () => loadOlder();
    $('drawer').addEventListener('close', () => { drawer = null; cardDrawer = null; drawerRequest++; });
    for (const id of ['matters-list', 'cards', 'rules-list', 'history-list', 'overview', 'flow']) {
        $(id).addEventListener('focusout', () => setTimeout(render, 0));
    }
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') refresh();
    });
    window.addEventListener('offline', () => {
        stream?.close();
        stream = undefined;
        clearTimeout(reconnect);
        reconnect = undefined;
        connection = state ? 'stale' : 'offline';
        renderHealth();
    });
    window.addEventListener('online', () => {
        if (state) subscribe(applied);
        else refresh();
    });
    // Refresh sparse presence/day boundaries when no fact was written, rather than poll active runs.
    setInterval(() => {
        updateWaiting();
        if (state && (day(Date.now()) !== day(state.now) || state.agents.concat(state.channels)
            .some((entry) => entry.online && entry.seenAt && Date.now() - Date.parse(entry.seenAt) > 180000))) refresh();
    }, 30000);
    render();
    refresh().then(() => {
        if (initialCursor && state) loadOlder(initialCursor);
        if (view === 'matter') {
            const item = args.get('item');
            if (item || initialRun) openMatter(item ? `item=${encodeURIComponent(item)}` : `run=${initialRun}`, true);
            else $('matter-page').replaceChildren(empty('请从工作流总览选择事项。'));
        } else if (initialRun) openRun(initialRun);
    });
})();
