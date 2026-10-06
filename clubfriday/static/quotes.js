/* Break only at Thai word boundaries; never translate, summarise, or drop characters. */
(function(root) {
  function breakLines(text, count) {
    const flat = text.replace(/\r?\n/g, "");
    const words = Array.from(new Intl.Segmenter("th", {granularity: "word"}).segment(flat), s => s.segment);
    const lines = [];
    let remaining = flat.length, line = "";
    for (const word of words) {
      const slots = count - lines.length;
      const target = remaining / slots;
      if (slots > 1 && line && line.length + word.length > target && line.length >= target / 2) {
        lines.push(line); remaining -= line.length; line = "";
      }
      line += word;
    }
    if (line) lines.push(line);
    return lines;
  }
  function timestamp(ms) {
    const seconds = Math.floor(ms / 1000);
    return `${String(Math.floor(seconds / 3600)).padStart(2,"0")}:${String(Math.floor(seconds / 60) % 60).padStart(2,"0")}:${String(seconds % 60).padStart(2,"0")}.${String(ms % 1000).padStart(3,"0")}`;
  }
  const api = {breakLines, timestamp};
  if (typeof module !== "undefined") module.exports = api;
  else root.ClubFridayQuotes = api;
})(globalThis);
