/* Co-Scientist UI behaviour.
 *
 * Replaces the htmx CDN script. Everything the old markup did with hx-post is
 * three fetch calls and a toast, and dropping the dependency is what lets the
 * UI load with no network — the same local-first posture as the daemon itself.
 */

(function () {
    "use strict";

    function toast(message, isError) {
        var el = document.createElement("div");
        el.className = "toast" + (isError ? " err" : "");
        el.textContent = message;
        document.body.appendChild(el);
        setTimeout(function () { el.remove(); }, 3200);
    }

    /* data-post="/api/…" — POST, optionally confirm first, then reload. */
    document.addEventListener("click", function (ev) {
        var btn = ev.target.closest("[data-post]");
        if (!btn) return;
        ev.preventDefault();
        var ask = btn.getAttribute("data-confirm");
        if (ask && !window.confirm(ask)) return;

        btn.disabled = true;
        fetch(btn.getAttribute("data-post"), { method: "POST" })
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                toast(btn.getAttribute("data-done") || "Done");
                if (btn.hasAttribute("data-reload")) {
                    setTimeout(function () { location.reload(); }, 550);
                }
            })
            .catch(function (e) { toast(e.message, true); })
            .finally(function () { btn.disabled = false; });
    });

    /* Forms marked data-async post as form-encoded and stay on the page. */
    document.addEventListener("submit", function (ev) {
        var form = ev.target;
        if (!form.hasAttribute("data-async")) return;
        ev.preventDefault();
        var submit = form.querySelector("[type=submit]");
        if (submit) submit.disabled = true;

        fetch(form.action, { method: "POST", body: new FormData(form) })
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                toast(form.getAttribute("data-done") || "Sent");
                form.reset();
            })
            .catch(function (e) { toast(e.message, true); })
            .finally(function () { if (submit) submit.disabled = false; });
    });

    /* Live event stream. Renders into #events-log and nudges the counters. */
    var log = document.getElementById("events-log");
    if (!log) return;
    var sessionId = log.getAttribute("data-session");
    if (!sessionId) return;

    var NAMES = [
        "session_started", "task_started", "task_completed", "task_failed",
        "hypothesis_created", "review_completed", "match_complete",
        "tournament_match_complete", "session_done", "human_feedback",
        "session_paused", "session_resumed", "session_aborted"
    ];
    /* Events that change the leaderboard. Reload rather than patch rows: the
     * ordering is Elo-sorted server-side and re-deriving it here would be a
     * second source of truth. Debounced so a burst of matches is one reload. */
    var RELOADERS = ["hypothesis_created", "session_done", "review_completed"];
    var pending = null;

    function push(name, payload) {
        var li = document.createElement("li");
        var t = document.createElement("span");
        t.className = "t";
        t.textContent = new Date().toTimeString().slice(0, 8);
        var n = document.createElement("span");
        n.className = "n";
        n.textContent = name.replace(/_/g, " ");
        var d = document.createElement("span");
        d.className = "d";
        d.textContent = payload ? summarise(payload) : "";
        li.append(t, n, d);
        log.insertBefore(li, log.firstChild);
        while (log.children.length > 80) log.removeChild(log.lastChild);
    }

    /* Keep the one or two fields that matter per event type; the full JSON
     * blob was unreadable at this width. */
    function summarise(p) {
        var body = p && p.payload ? p.payload : p;
        if (!body || typeof body !== "object") return String(body || "");
        var bits = [];
        if (body.title) bits.push(body.title);
        if (body.agent) bits.push(body.agent);
        if (body.winner) bits.push("winner " + body.winner);
        if (body.elo_a !== undefined) {
            bits.push(Math.round(body.elo_a) + " / " + Math.round(body.elo_b));
        }
        if (body.stop_reason) bits.push(body.stop_reason);
        if (body.text) bits.push(body.text);
        if (!bits.length && body.task_id) bits.push(body.task_id.slice(-6));
        if (!bits.length) {
            var s = JSON.stringify(body);
            return s.length > 90 ? s.slice(0, 90) + "…" : s;
        }
        return bits.join(" · ");
    }

    var es = new EventSource("/api/sessions/" + sessionId + "/events");
    NAMES.forEach(function (name) {
        es.addEventListener(name, function (e) {
            var parsed = null;
            try { parsed = JSON.parse(e.data); } catch (_) { parsed = e.data; }
            push(name, parsed);
            if (RELOADERS.indexOf(name) !== -1) {
                clearTimeout(pending);
                pending = setTimeout(function () { location.reload(); }, 2500);
            }
        });
    });
    es.onerror = function () { push("stream disconnected", null); };
})();
