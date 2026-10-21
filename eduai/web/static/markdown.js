/* Minimal, safe Markdown for model answers.
 *
 * parseBlocks / parseInline turn text into plain data (testable in Node);
 * render() builds DOM nodes using textContent only, so model output can never
 * inject HTML or scripts. Supports what tutoring answers use: fenced code
 * (also unfinished ones while streaming), headings, lists, tables, quotes,
 * rules, paragraphs, **bold**, *italic* and `inline code`.
 */
(function (root) {
  "use strict";

  const FENCE = /^\s*```\s*([\w+#.-]*)\s*$/;
  const HEADING = /^(#{1,6})\s+(.*)$/;
  const BULLET = /^\s*[-*+]\s+(.*)$/;
  const NUMBERED = /^\s*(\d+)[.)]\s+(.*)$/;
  const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
  const TABLE_ROW = /^\s*\|.*\|\s*$/;
  const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function splitRow(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
  }

  function parseBlocks(text) {
    const lines = text.replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let paragraph = [];

    const flush = () => {
      if (paragraph.length) blocks.push({ type: "paragraph", text: paragraph.join("\n") });
      paragraph = [];
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const fence = line.match(FENCE);
      if (fence) {
        flush();
        const code = [];
        let closed = false;
        for (i++; i < lines.length; i++) {
          if (FENCE.test(lines[i]) && !lines[i].trim().slice(3).trim()) { closed = true; break; }
          code.push(lines[i]);
        }
        blocks.push({ type: "code", lang: fence[1].toLowerCase(), text: code.join("\n"), closed });
        continue;
      }
      if (!line.trim()) { flush(); continue; }
      const heading = line.match(HEADING);
      if (heading) { flush(); blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim() }); continue; }
      if (RULE.test(line)) { flush(); blocks.push({ type: "rule" }); continue; }
      if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1])) {
        flush();
        const header = splitRow(line);
        const rows = [];
        for (i += 2; i < lines.length && TABLE_ROW.test(lines[i]); i++) rows.push(splitRow(lines[i]));
        i--;
        blocks.push({ type: "table", header, rows });
        continue;
      }
      const bullet = line.match(BULLET);
      const numbered = line.match(NUMBERED);
      if (bullet || numbered) {
        flush();
        const ordered = Boolean(numbered);
        const start = ordered ? parseInt(numbered[1], 10) : 1;
        const items = [];
        for (; i < lines.length; i++) {
          const m = ordered ? lines[i].match(NUMBERED) : lines[i].match(BULLET);
          if (m) { items.push(ordered ? m[2] : m[1]); continue; }
          // Indented continuation line belongs to the previous item.
          if (items.length && /^\s{2,}\S/.test(lines[i]) && !FENCE.test(lines[i])) { items[items.length - 1] += " " + lines[i].trim(); continue; }
          break;
        }
        i--;
        blocks.push({ type: "list", ordered, start, items });
        continue;
      }
      if (/^\s*>/.test(line)) {
        flush();
        const quote = [];
        for (; i < lines.length && /^\s*>/.test(lines[i]); i++) quote.push(lines[i].replace(/^\s*>\s?/, ""));
        i--;
        blocks.push({ type: "quote", text: quote.join("\n") });
        continue;
      }
      paragraph.push(line);
    }
    flush();
    return blocks;
  }

  // Inline: `code` first (its contents are literal), then **bold**, then *italic*.
  function parseInline(text) {
    const tokens = [];
    const pattern = /(`+)([^`]+?)\1|\*\*(.+?)\*\*|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g;
    let last = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > last) tokens.push({ type: "text", text: text.slice(last, match.index) });
      if (match[2] !== undefined) tokens.push({ type: "code", text: match[2] });
      else if (match[3] !== undefined) tokens.push({ type: "bold", children: parseInline(match[3]) });
      else tokens.push({ type: "italic", children: parseInline(match[4]) });
      last = pattern.lastIndex;
    }
    if (last < text.length) tokens.push({ type: "text", text: text.slice(last) });
    return tokens;
  }

  // ---------------------------------------------------------------- DOM ----
  function el(doc, tag, className, text) {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function appendTokens(doc, parent, tokens) {
    for (const token of tokens) {
      if (token.type === "text") {
        // Keep the model's single line breaks inside a paragraph.
        token.text.split("\n").forEach((part, i) => {
          if (i) parent.appendChild(doc.createElement("br"));
          parent.appendChild(doc.createTextNode(part));
        });
      } else if (token.type === "code") {
        parent.appendChild(el(doc, "code", "inline", token.text));
      } else {
        const node = doc.createElement(token.type === "bold" ? "strong" : "em");
        appendTokens(doc, node, token.children);
        parent.appendChild(node);
      }
    }
  }

  function appendInline(doc, parent, text) {
    appendTokens(doc, parent, parseInline(text));
  }

  function codeBlock(doc, block, hljs) {
    const wrap = el(doc, "div", "code-block");
    const bar = el(doc, "div", "code-bar");
    bar.appendChild(el(doc, "span", "code-lang", block.lang || "code"));
    const copy = el(doc, "button", "copy", "Copy");
    copy.type = "button";
    copy.dataset.copy = block.text;
    bar.appendChild(copy);
    const pre = doc.createElement("pre");
    const code = el(doc, "code");
    if (hljs && block.lang && hljs.getLanguage(block.lang)) {
      // highlight.js escapes the source text itself, so its HTML output is safe.
      code.innerHTML = hljs.highlight(block.text, { language: block.lang, ignoreIllegals: true }).value;
      code.className = "hljs language-" + block.lang;
    } else {
      code.textContent = block.text;
      code.className = "hljs";
    }
    pre.appendChild(code);
    wrap.appendChild(bar);
    wrap.appendChild(pre);
    return wrap;
  }

  function render(text, doc, hljs) {
    const fragment = doc.createDocumentFragment();
    for (const block of parseBlocks(text)) {
      if (block.type === "code") fragment.appendChild(codeBlock(doc, block, hljs));
      else if (block.type === "heading") {
        const h = doc.createElement("h" + Math.min(block.level + 2, 6)); // keep headings modest inside a chat
        appendInline(doc, h, block.text);
        fragment.appendChild(h);
      } else if (block.type === "rule") fragment.appendChild(doc.createElement("hr"));
      else if (block.type === "list") {
        const list = doc.createElement(block.ordered ? "ol" : "ul");
        if (block.ordered && block.start !== 1) list.start = block.start;
        for (const item of block.items) {
          const li = doc.createElement("li");
          appendInline(doc, li, item);
          list.appendChild(li);
        }
        fragment.appendChild(list);
      } else if (block.type === "table") {
        const scroll = el(doc, "div", "table-scroll");
        const table = doc.createElement("table");
        const head = doc.createElement("tr");
        for (const cell of block.header) { const th = doc.createElement("th"); appendInline(doc, th, cell); head.appendChild(th); }
        const thead = doc.createElement("thead");
        thead.appendChild(head);
        table.appendChild(thead);
        const tbody = doc.createElement("tbody");
        for (const row of block.rows) {
          const tr = doc.createElement("tr");
          for (const cell of row) { const td = doc.createElement("td"); appendInline(doc, td, cell); tr.appendChild(td); }
          tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        scroll.appendChild(table);
        fragment.appendChild(scroll);
      } else if (block.type === "quote") {
        const quote = doc.createElement("blockquote");
        appendInline(doc, quote, block.text);
        fragment.appendChild(quote);
      } else {
        const p = doc.createElement("p");
        appendInline(doc, p, block.text);
        fragment.appendChild(p);
      }
    }
    return fragment;
  }

  const api = { parseBlocks, parseInline, render };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.EduMarkdown = api;
})(typeof window !== "undefined" ? window : globalThis);
