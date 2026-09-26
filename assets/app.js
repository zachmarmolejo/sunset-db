window.SunsetDB = (() => {
  let topics = null;

  async function load() {
    if (topics) return topics;
    const res = await fetch("content/topics.json", { cache: "no-store" });
    if (!res.ok) throw new Error("Could not load content/topics.json — serve via HTTP (see README).");
    topics = await res.json();
    return topics;
  }

  function haystack(t) {
    const snip = Object.entries(t.snippets || {})
      .map(([lang, s]) => [lang, s.code || "", s.notes || ""].join(" "))
      .join(" ");
    return [
      t.title, t.summary || "", t.when_to_use || "",
      (t.tags || []).join(" "), (t.languages || []).join(" "),
      t.category || "", t.os || "", snip,
      (t.pitfalls || []).join(" ")
    ].join("\n").toLowerCase();
  }

  function filter(all, { q, lang, os, cat } = {}) {
    const qq = (q || "").trim().toLowerCase();
    return all.filter(t => {
      if (lang && !(t.languages || []).includes(lang)) return false;
      if (os && t.os !== os && t.os !== "both") return false;
      if (cat && t.category !== cat) return false;
      if (!qq) return true;
      return haystack(t).includes(qq);
    });
  }

  function fillSelect(sel, values, allLabel) {
    const keep = sel.value;
    sel.innerHTML = "";
    const o0 = document.createElement("option");
    o0.value = ""; o0.textContent = allLabel;
    sel.appendChild(o0);
    [...values].sort().forEach(v => {
      const o = document.createElement("option");
      o.value = v; o.textContent = v;
      sel.appendChild(o);
    });
    sel.value = keep;
  }

  function collectMeta(all) {
    const langs = new Set(), cats = new Set(), oses = new Set();
    all.forEach(t => {
      (t.languages || []).forEach(l => langs.add(l));
      if (t.category) cats.add(t.category);
      if (t.os && t.os !== "both") oses.add(t.os);
      else if (t.os === "both") { oses.add("windows"); oses.add("linux"); }
    });
    // Always offer both platforms in the filter
    oses.add("windows");
    oses.add("linux");
    return { langs, cats, oses };
  }

  function chips(t, el) {
    (t.languages || []).forEach(l => {
      const s = document.createElement("span");
      s.className = "chip lang"; s.textContent = l; el.appendChild(s);
    });
    if (t.os) {
      const s = document.createElement("span");
      s.className = "chip os"; s.textContent = t.os; el.appendChild(s);
    }
    if (t.category) {
      const s = document.createElement("span");
      s.className = "chip"; s.textContent = t.category; el.appendChild(s);
    }
    (t.tags || []).slice(0, 3).forEach(tag => {
      const s = document.createElement("span");
      s.className = "chip"; s.textContent = tag; el.appendChild(s);
    });
  }

  function esc(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

  function detailUrl(id) {
    return `topic.html?id=${encodeURIComponent(id)}`;
  }

  function highlight(root) {
    if (!window.hljs) return;
    root.querySelectorAll("pre code").forEach(b => hljs.highlightElement(b));
  }

  const LANG_ORDER = ["c", "go", "rust", "python"];

  function orderedSnippets(t) {
    const sn = t.snippets || {};
    const keys = [
      ...LANG_ORDER.filter(l => sn[l]),
      ...Object.keys(sn).filter(k => !LANG_ORDER.includes(k)).sort()
    ];
    return keys.map(k => ({ language: k, ...sn[k] }));
  }

  return {
    load, filter, fillSelect, collectMeta, chips, esc,
    detailUrl, highlight, haystack, orderedSnippets, LANG_ORDER
  };
})();
