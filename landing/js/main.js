/**
 * Page-level wiring: scroll-triggered reveals, sticky bar toggle, and
 * the interest-form submit handler.
 *
 * Audio playback is owned by demo-adaptive.js (use case 01) and
 * demo-stems.js (use case 02). Each manages its own StemMixer instance
 * and DOM controls.
 *
 * Analytics events are fired through Vercel Analytics' `window.va`.
 * The wrapper is a no-op when VA isn't present (local dev, other hosts),
 * so the same code works in every environment.
 */

function track(name, props = {}) {
    try {
        window.va?.("event", { name, ...props });
    } catch (_) { /* never let analytics break the UX */ }
}
window.__track = track;  // exposed for demo modules

/** Fade-in + lift sections as they scroll into view. One-shot per element. */
function wireScrollReveal() {
    const targets = document.querySelectorAll("[data-reveal]");
    if (!("IntersectionObserver" in window) || targets.length === 0) {
        targets.forEach(el => el.classList.add("is-visible"));
        return;
    }
    const obs = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-visible");
                obs.unobserve(entry.target);
            }
        }
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    targets.forEach(el => obs.observe(el));
}

/** Show the sticky condensed header once the hero scrolls out of view. */
function wireStickyBar() {
    const bar = document.getElementById("sticky-bar");
    const hero = document.querySelector(".hero");
    if (!bar || !hero || !("IntersectionObserver" in window)) return;
    const obs = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            bar.dataset.visible = entry.isIntersecting ? "false" : "true";
        }
    }, { rootMargin: "-40% 0px 0px 0px", threshold: 0 });
    obs.observe(hero);
}

function wireInterestForm() {
    const form = document.getElementById("interest-form");
    const status = document.getElementById("interest-status");
    if (!form || !status) return;

    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const email = form.email.value.trim();
        if (!email) return;

        if (form.action.includes("YOUR_FORM_ID")) {
            status.hidden = false;
            status.textContent =
                "Form not wired yet — set up a Formspree form and replace " +
                "YOUR_FORM_ID in index.html.";
            status.dataset.kind = "error";
            return;
        }

        status.hidden = false;
        status.textContent = "Sending…";
        status.dataset.kind = "info";

        try {
            const resp = await fetch(form.action, {
                method: "POST",
                headers: { Accept: "application/json" },
                body: new FormData(form),
            });
            if (resp.ok) {
                form.reset();
                status.textContent = "Got it — I'll be in touch when there's something to try.";
                status.dataset.kind = "ok";
                track("signup");
            } else {
                status.textContent = `Couldn't submit (HTTP ${resp.status}). Try again later.`;
                status.dataset.kind = "error";
            }
        } catch (err) {
            status.textContent = `Network error: ${err.message}`;
            status.dataset.kind = "error";
        }
    });
}

function main() {
    wireScrollReveal();
    wireStickyBar();
    wireInterestForm();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", main);
} else {
    main();
}
