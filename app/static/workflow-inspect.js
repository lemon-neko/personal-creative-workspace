(() => {
    const feedback = document.getElementById('inspect-feedback');
    document.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-copy], [data-copy-target]');
        if (!button) return;
        const text = button.dataset.copy ?? document.getElementById(button.dataset.copyTarget)?.textContent;
        try {
            await navigator.clipboard.writeText(text);
            feedback.textContent = '已复制';
        } catch {
            feedback.textContent = '复制未完成，可手动选中文字。';
        }
    });

    const execution = document.getElementById('execution-events');
    if (execution) {
        const events = [...execution.children].sort((a, b) =>
            Number(a.dataset.at ?? Infinity) - Number(b.dataset.at ?? Infinity));
        execution.replaceChildren(...events);
        const kind = document.getElementById('execution-kind');
        const search = document.getElementById('execution-search');
        const filter = () => {
            const term = search.value.trim().toLocaleLowerCase();
            for (const row of events) {
                row.hidden = (kind.value && kind.value !== row.dataset.executionKind)
                    || !row.textContent.toLocaleLowerCase().includes(term);
            }
            document.getElementById('execution-empty').hidden = events.some((row) => !row.hidden);
        };
        kind.addEventListener('change', filter);
        search.addEventListener('input', filter);
        filter();
    }

    const replay = document.getElementById('run-replay');
    if (!replay) return;
    const frames = JSON.parse(document.getElementById('replay-data').content.textContent);
    const current = document.getElementById('replay-current');
    const steps = document.getElementById('replay-steps');
    const json = document.getElementById('replay-json');
    const position = document.getElementById('replay-position');
    const [previous, play, next] = replay.querySelectorAll('[data-replay]');
    const labels = { queued: '排队中', claimed: '已领取', unknown: '状态不确定', done: '本轮已结束', nothing: '无事可做', cancelled: '已取消' };
    const time = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'medium' });
    let timer;
    function stop() {
        clearInterval(timer);
        timer = undefined;
        play.textContent = '播放';
    }
    function show(index) {
        position.value = index;
        const frame = frames[index];
        const known = frames.slice(0, index + 1).findLast((entry) => entry.run)?.run;
        const state = known?.state;
        current.textContent = `Fact #${frame.seq} · ${time.format(frame.at)} · ${labels[state] ?? '状态未记录'}`;
        position.setAttribute('aria-valuetext', `Fact ${frame.seq}`);
        json.textContent = JSON.stringify(frame, null, 2);
        steps.replaceChildren(...frame.steps.map((step) => {
            const row = document.createElement('li');
            row.textContent = [step.factType, step.summary || step.title || step.error || step.rule || step.kind].join(' · ');
            return row;
        }));
        previous.disabled = index === 0;
        next.disabled = index === frames.length - 1;
        if (next.disabled) stop();
        play.disabled = frames.length < 2;
    }
    previous.onclick = () => { stop(); show(Number(position.value) - 1); };
    next.onclick = () => { stop(); show(Number(position.value) + 1); };
    position.oninput = () => { stop(); show(Number(position.value)); };
    play.onclick = () => {
        if (timer) { stop(); return; }
        if (next.disabled) show(0);
        play.textContent = '暂停';
        timer = setInterval(() => show(Number(position.value) + 1), 800);
    };
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
    show(0);
})();
