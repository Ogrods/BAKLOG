/**
 * Landing page utilities: footer year, waitlist form.
 */
(function () {
  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  const form = document.getElementById("waitlist");
  if (!form) return;

  const emailEl = document.getElementById("email");
  const btn = document.getElementById("submitBtn");
  const msg = document.getElementById("formMsg");
  const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.className = "form-msg";
    msg.textContent = "";

    const email = emailEl.value.trim();
    if (!EMAIL_RE.test(email)) {
      msg.className = "form-msg err";
      msg.textContent = "Please enter a valid email.";
      emailEl.focus();
      return;
    }

    const website = form.elements["website"].value;
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "Sending…";

    try {
      const res = await fetch("/api/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, website }),
      });
      if (!res.ok) throw new Error("bad status");
      form.querySelector(".waitlist-row").remove();
      form.querySelector(".form-reassure").remove();
      msg.className = "form-msg ok";
      msg.textContent =
        "Check your inbox for the download link. The open beta is ready now.";
    } catch {
      btn.disabled = false;
      btn.textContent = original;
      msg.className = "form-msg err";
      msg.textContent = "Something went wrong. Please try again in a moment.";
    }
  });
})();
