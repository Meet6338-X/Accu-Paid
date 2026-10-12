/* AccuPaid site behaviors: nav, reveal, demo typing, FormSubmit validation. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Mobile nav: toggle + Escape + focus return.
  var toggle = document.getElementById("nav-toggle");
  var nav = document.getElementById("nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("open")) {
        nav.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      }
    });
  }

  // Stagger reveal (skip entirely under reduced-motion).
  if (!reduced && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en, i) {
        if (en.isIntersecting) {
          setTimeout(function () { en.target.classList.add("on"); }, i * 90);
          io.unobserve(en.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll("#platform article, #how li, #flow li, #pricing article, .stat").forEach(function (el) {
      el.classList.add("reveal");
      io.observe(el);
    });
  }

  // ---- Pilot form: native + inline validation, honeypot, FormSubmit ----
  var form = document.getElementById("pilot-form");
  if (!form) return;
  var send = document.getElementById("send");
  var summary = document.getElementById("form-err");
  var okBox = document.getElementById("form-ok");
  var emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function setErr(id, msg) {
    var p = document.getElementById(id + "-err");
    var f = document.getElementById(id);
    if (msg) {
      if (p) { p.textContent = msg; p.hidden = false; }
      if (f) f.setAttribute("aria-invalid", "true");
      return false;
    }
    if (p) { p.textContent = ""; p.hidden = true; }
    if (f) f.removeAttribute("aria-invalid");
    return true;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    okBox.hidden = true;
    summary.hidden = true;
    // Honeypot: bots fill it; humans can't see it. Silent drop.
    var hp = form.querySelector('input[name="_honey"]');
    if (hp && hp.value) return;

    var name = document.getElementById("f-name").value.trim();
    var email = document.getElementById("f-email").value.trim();
    var company = document.getElementById("f-company").value.trim();
    var head = document.getElementById("f-head").value;
    var msg = document.getElementById("f-msg").value.trim();

    var v = [
      setErr("f-name", name.length >= 2 ? "" : "Please enter your name."),
      setErr("f-email", emailRe.test(email) ? "" : "Enter a valid work email."),
      setErr("f-company", company.length >= 2 ? "" : "Please enter your company."),
      setErr("f-head", head ? "" : "Select your headcount range."),
      setErr("f-msg", msg.length >= 10 ? "" : "Tell us a little more (10+ characters).")
    ];
    if (v.indexOf(false) !== -1) {
      summary.textContent = "Please fix the highlighted fields.";
      summary.hidden = false;
      var firstBad = form.querySelector("[aria-invalid]");
      if (firstBad) firstBad.focus();
      return;
    }
    send.disabled = true;
    send.textContent = "Sending…";
    fetch(form.action, { method: "POST", body: new FormData(form), headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("submit failed");
        okBox.textContent = "Thanks — your pilot request is in. We reply with a checklist within 2 business days.";
        okBox.hidden = false;
        form.reset();
      })
      .catch(function () {
        // Fallback: native submit (full-page POST to FormSubmit).
        form.submit();
      })
      .finally(function () {
        send.disabled = false;
        send.textContent = "Request pilot";
      });
  });
})();
