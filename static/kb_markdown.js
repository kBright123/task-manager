// 轻量 markdown 渲染:优先 marked+DOMPurify,CDN 失败时用内置降级渲染器。
// 避免纯文本 + pre-wrap 导致回答"一行一条竖着排列"。
window.renderMarkdown = function (text) {
  if (window.marked && window.DOMPurify) {
    try {
      return DOMPurify.sanitize(marked.parse(String(text || '')));
    } catch (e) {}
  }
  return null;
};

window.mdLite = function (input) {
  var t = String(input == null ? '' : input);
  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function inline(s) {
    s = esc(s);
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return s;
  }
  var lines = t.split('\n');
  var html = [];
  var list = null;
  function flushList() {
    if (list) { html.push(list === 'ul' ? '</ul>' : '</ol>'); list = null; }
  }
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    var m;
    if (!line.trim()) { flushList(); html.push('<p></p>'); continue; }
    if (/^```/.test(line)) {
      flushList();
      var code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        code.push(esc(lines[i]));
        i++;
      }
      html.push('<pre><code>' + code.join('\n') + '</code></pre>');
      continue;
    }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      flushList();
      var h = m[1].length;
      html.push('<h' + h + '>' + inline(m[2]) + '</h' + h + '>');
      continue;
    }
    if (/^\s*(?:[-*]|\d+[.)])\s+/.test(line)) {
      var ol = /^\s*\d+[.)]\s+/.test(line);
      var tag = ol ? 'ol' : 'ul';
      if (list !== tag) { flushList(); list = tag; html.push('<' + tag + '>'); }
      html.push('<li>' + inline(line.replace(/^\s*(?:[-*]|\d+[.)])\s+/, '')) + '</li>');
      continue;
    }
    flushList();
    html.push('<p>' + inline(line) + '</p>');
  }
  flushList();
  return html.join('\n');
};
