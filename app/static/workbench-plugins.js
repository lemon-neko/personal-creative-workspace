const frame = document.querySelector(".daily-frame");
if (frame) {
    const origin = new URL(frame.src).origin;
    const message = document.querySelector("#daily-message");
    let handingOff = false;
    let snapshotRequest;
    const snapshotUrl = frame.dataset.mobileSnapshot;
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
    function requestSnapshot() {
        if (!snapshotUrl || !navigator.onLine || document.hidden) return;
        snapshotRequest = crypto.randomUUID();
        frame.contentWindow?.postMessage({type: "yubai.daily.request", id: snapshotRequest}, origin);
    }

    window.addEventListener("message", async (event) => {
        const data = event.data;
        if (event.origin !== origin || event.source !== frame.contentWindow) return;
        if (data?.type === "yubai.daily.ready") {
            requestSnapshot();
            return;
        }
        if (snapshotUrl && data?.type === "yubai.daily.snapshot" && snapshotRequest && data.id === snapshotRequest) {
            snapshotRequest = undefined;
            try {
                await fetch(snapshotUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
                    body: JSON.stringify(data.snapshot),
                });
            } catch (_) {
                // Keep the last valid snapshot while the desktop is offline.
            }
            return;
        }
        if (data?.type !== "yubai.task" || typeof data.id !== "string" || typeof data.title !== "string" || handingOff) return;
        handingOff = true;
        try {
            const response = await fetch(frame.dataset.handoff, {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
                body: JSON.stringify({id: data.id, title: data.title}),
            });
            if (!response.ok) throw new Error();
            const {url} = await response.json();
            location.assign(url);
        } catch {
            message.textContent = "暂时无法交接任务，请稍后重试。";
            message.hidden = false;
        } finally {
            handingOff = false;
        }
    });
    if (snapshotUrl) {
        frame.addEventListener("load", requestSnapshot);
        document.addEventListener("visibilitychange", requestSnapshot);
        window.addEventListener("online", requestSnapshot);
        window.setInterval(requestSnapshot, 60_000);
        requestSnapshot();
    }
}
