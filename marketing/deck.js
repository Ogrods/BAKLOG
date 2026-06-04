(function () {
  const reveals = document.querySelectorAll(".reveal");
  const navLinks = document.querySelectorAll(".nav-links a[data-section]");
  const sections = [...document.querySelectorAll("section[id]")];

  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) e.target.classList.add("is-visible");
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
  );
  reveals.forEach((el) => io.observe(el));

  const navIo = new IntersectionObserver(
    (entries) => {
      const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      const id = visible.target.id;
      navLinks.forEach((a) => {
        a.classList.toggle("is-active", a.dataset.section === id);
      });
    },
    { rootMargin: "-40% 0px -50% 0px", threshold: [0, 0.25, 0.5] }
  );
  sections.forEach((s) => navIo.observe(s));
})();
