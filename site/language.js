// Both editions are static pages. The root also serves as the language-neutral entry point.
(() => {
  const current = document.documentElement.lang;
  const url = new URL(location.href);
  const requested = url.searchParams.get("lang");
  const key = "as-built-atlas:lp-language";
  const supported = ["ja", "en"];
  let saved;
  try {
    if (supported.includes(requested)) localStorage.setItem(key, requested);
    saved = localStorage.getItem(key);
  } catch {
    // Private browsing or a storage policy can disable preferences.
  }

  const languages = navigator.languages?.length ? navigator.languages : [navigator.language];
  const preferred = languages.map(tag => tag.toLowerCase().split("-")[0])
    .find(language => supported.includes(language));
  const rootDefault = supported.includes(saved) ? saved : preferred || "en";
  const target = supported.includes(requested) ? requested : current === "en" ? "en" : rootDefault;
  if (target === current) return;
  const destination = new URL(target === "en" ? "./en/" : "../", url);
  destination.search = url.search;
  destination.hash = url.hash;
  location.replace(destination);
})();
