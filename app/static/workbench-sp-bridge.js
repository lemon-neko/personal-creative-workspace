// Loaded by the bundled Super Productivity plugin on its own local origin.
const registerHandoff = () => PluginAPI.registerTaskContextMenuEntry({
    id: "yubai-send-task",
    label: document.documentElement.lang === "en" ? "Send to AI" : "交给 AI",
    icon: "auto_awesome",
    onClick: async ({taskId}) => {
        const task = (await PluginAPI.getTasks()).find(({id}) => id === taskId);
        if (task) window.parent.postMessage({type: "yubai.task", id: task.id, title: task.title.slice(0, 200)}, "http://127.0.0.1:8765");
    },
});
registerHandoff();
const languageObserver = new MutationObserver(registerHandoff);
languageObserver.observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
PluginAPI.onUnload(() => languageObserver.disconnect());

const workbenchOrigin = "http://127.0.0.1:8765";
const dateFormat = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
});
const timeFormat = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const isTimestamp = value => Number.isFinite(value) && value > 0 && value <= 8.64e15;
const boardSnapshot = async event => {
    if (event.origin !== workbenchOrigin || event.source !== window.parent
        || event.data?.type !== "yubai.daily.request" || typeof event.data.id !== "string") return;
    try {
        const day = dateFormat.format(new Date());
        const groups = {today: [], overdue: [], unplanned: [], done: []};
        for (const task of await PluginAPI.getTasks()) {
            const title = typeof task.title === "string" ? task.title.trim().slice(0, 200) : "";
            if (!title) continue;
            const timed = isTimestamp(task.dueWithTime);
            const due = timed ? dateFormat.format(task.dueWithTime) : task.dueDay;
            if (task.isDone) {
                if (isTimestamp(task.doneOn) && dateFormat.format(task.doneOn) === day) {
                    groups.done.push({title, when: timeFormat.format(task.doneOn)});
                }
            } else if (due === day) {
                groups.today.push({title, when: timed ? timeFormat.format(task.dueWithTime) : ""});
            } else if (typeof due === "string" && /^\d{4}-\d{2}-\d{2}$/.test(due) && due < day) {
                groups.overdue.push({title, when: due});
            } else if (!due) {
                groups.unplanned.push({title});
            }
        }
        for (const name of Object.keys(groups)) {
            groups[name] = groups[name]
                .sort((a, b) => (a.when || "").localeCompare(b.when || ""))
                .slice(0, 40);
        }
        window.parent.postMessage({
            type: "yubai.daily.snapshot", id: event.data.id, snapshot: {day, ...groups},
        }, workbenchOrigin);
    } catch (_) {
        // The next desktop request can retry when the task store is available.
    }
};
window.addEventListener("message", boardSnapshot);
PluginAPI.onUnload(() => window.removeEventListener("message", boardSnapshot));
if (window.parent !== window) window.parent.postMessage({type: "yubai.daily.ready"}, workbenchOrigin);
