(() => {
  const hero = document.querySelector("[data-dd-home-hero]");
  if (!hero) return;

  const update = () => {
    const rect = hero.getBoundingClientRect();
    const viewport = window.innerHeight || 1;
    const progress = Math.max(0, Math.min(1.6, -rect.top / viewport));
    hero.style.setProperty("--dd-hero-scroll", String(progress));
  };

  update();
  window.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);
})();
