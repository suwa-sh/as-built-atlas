// HTML だけでも4つの手順を順に読める。スクリプトが動くと同じ内容をタブで切り替える。
const controls = document.querySelector(".step-controls");
const buttons = Array.from(controls.querySelectorAll("button"));
const panels = buttons.map((button) => document.getElementById(button.dataset.panel));

const languageLink = document.querySelector(".language-link");
const languageURL = new URL(languageLink.href);

function updateLanguageLink() {
  languageURL.hash = location.hash;
  languageLink.href = languageURL.href;
}

updateLanguageLink();
window.addEventListener("hashchange", updateLanguageLink);

function selectStep(index) {
  showStep(index);
  history.replaceState(history.state, "", "#" + panels[index].id);
  updateLanguageLink();
}

function showStep(index) {
  buttons.forEach((button, i) => {
    const selected = i === index;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    panels[i].hidden = !selected;
  });
}

controls.setAttribute("role", "tablist");
buttons.forEach((button, index) => {
  const panel = panels[index];
  button.id = "tab-" + panel.id;
  button.setAttribute("role", "tab");
  button.setAttribute("aria-controls", panel.id);
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-labelledby", button.id);
  panel.tabIndex = 0;
  button.addEventListener("click", () => selectStep(index));
  button.addEventListener("keydown", (event) => {
    const target = {
      ArrowLeft: (index + buttons.length - 1) % buttons.length,
      ArrowRight: (index + 1) % buttons.length,
      Home: 0,
      End: buttons.length - 1,
    }[event.key];
    if (target === undefined) return;
    event.preventDefault();
    selectStep(target);
    buttons[target].focus();
  });
});
function openLinkedPanel() {
  const index = panels.findIndex((panel) => "#" + panel.id === location.hash);
  if (index < 0) return;
  showStep(index);
  controls.scrollIntoView({ block: "start" });
}

showStep(0);
controls.hidden = false;
openLinkedPanel();
window.addEventListener("hashchange", openLinkedPanel);

function showPoster(toggle, still) {
  const hadFocus = document.activeElement === toggle;
  toggle.hidden = true;
  still.hidden = false;
  if (hadFocus) still.focus();
}

function enableHeroRotation() {
  const toggle = document.querySelector(".hero-rotation");
  const video = toggle.querySelector("video");
  const still = document.querySelector(".hero-media .sample-image");
  if (!video.canPlayType("video/mp4") || video.error) return;

  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let userWantsRotation;
  let inView = false;
  function updatePlayback() {
    if (inView && !document.hidden && (userWantsRotation ?? !motion.matches)) {
      // 自動再生を制限する端末でも、図を押せば再生を試せる。
      video.play().catch(updateAction);
    } else {
      video.pause();
    }
  }
  function updateAction() {
    const action = video.paused ? toggle.dataset.play : toggle.dataset.pause;
    toggle.setAttribute("aria-label", action);
    toggle.title = action;
  }
  toggle.addEventListener("click", () => {
    userWantsRotation = video.paused;
    updatePlayback();
  });
  video.addEventListener("play", updateAction);
  video.addEventListener("pause", updateAction);
  video.addEventListener("error", () => showPoster(toggle, still));
  motion.addEventListener("change", () => {
    if (motion.matches && userWantsRotation) userWantsRotation = undefined;
    updatePlayback();
  });
  document.addEventListener("visibilitychange", updatePlayback);
  still.hidden = true;
  toggle.hidden = false;
  updateAction();
  const playback = new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting;
    updatePlayback();
  });
  playback.observe(toggle);
}

function observePendingSections(observer) {
  // スクリプトの到着前に読めていた文章は消さず、これから出るものだけを準備する。
  const alreadyPainted =
    !("PerformancePaintTiming" in window) ||
    performance.getEntriesByName("first-contentful-paint", "paint").length > 0;
  const targets = document.querySelectorAll(
    "[data-reveal], .problems li, .concept-map, .process li, .step-panel",
  );
  for (const element of targets) {
    if (alreadyPainted) {
      const rect = element.getBoundingClientRect();
      if (rect.bottom > 0 && rect.top < document.documentElement.clientHeight) continue;
    }
    element.classList.add("reveal-pending");
    observer.observe(element);
  }
}

function revealReadingSections(visible, observer) {
  const height = document.documentElement.clientHeight;
  const remainingScroll = document.documentElement.scrollHeight - window.scrollY - height;
  // ページ末尾でも、最後の文章が到達できる位置で動かす。
  const readingLine = Math.max(height * 0.9, height - Math.max(0, remainingScroll));
  for (const element of visible) {
    const rect = element.getBoundingClientRect();
    const inset = Math.min(rect.height / 2, height * 0.12);
    if (!rect.height || rect.top + inset > readingLine || rect.bottom < inset) continue;
    element.classList.replace("reveal-pending", "in-view");
    observer.unobserve(element);
    visible.delete(element);
  }
}

function enableSectionReveals() {
  const visible = new Set();
  let timer = 0;
  function scheduleReveal() {
    if (timer || !visible.size) return;
    const startY = window.scrollY;
    timer = setTimeout(() => {
      timer = 0;
      // 速く通り過ぎる間は待ち、ゆっくり読み進めているときも再生する。
      if (Math.abs(window.scrollY - startY) > document.documentElement.clientHeight * 0.04) {
        scheduleReveal();
      } else {
        revealReadingSections(visible, observer);
      }
    }, 140);
  }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) visible.add(entry.target);
      else visible.delete(entry.target);
    }
    scheduleReveal();
  });
  window.addEventListener("scroll", scheduleReveal, { passive: true });
  window.addEventListener("resize", scheduleReveal);
  observePendingSections(observer);
}

if ("IntersectionObserver" in window) {
  enableHeroRotation();
  enableSectionReveals();
}
