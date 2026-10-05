/* 在隔离的预检 HTML 中运行：按 A4 版心和打印媒体测量，不修改交付 HTML。 */
window.addEventListener('load', () => {
  const output = document.createElement('script');
  output.id = 'finagent-render-check';
  output.type = 'application/json';
  try {
    // DOM 预检使用打印规则；最终 PDF 仍由 Chrome 原生打印生成。
    function printRules(rules) {
      for (const rule of rules) {
        if (rule.type === CSSRule.MEDIA_RULE) {
          const query = rule.conditionText;
          rule.media.mediaText = query.replace(/\bprint\b/g, 'screen').replace(/\bscreen\b/g, 'screen');
          if (/\bscreen\b/.test(query) && !/\bprint\b/.test(query)) rule.media.mediaText = 'not all';
          printRules(rule.cssRules);
        }
      }
    }
    for (const sheet of document.styleSheets) printRules(sheet.cssRules);
    const style = document.createElement('style');
    style.textContent = 'html {width:180mm !important; margin:0 !important;} body {width:180mm !important; margin:0 !important;}';
    document.head.append(style);
    const body = document.body.getBoundingClientRect();
    const overflow = [];
    const font_errors = [];
    const samples = [];
    const ignored = 'script,style,.toc-end';
    for (const e of document.body.querySelectorAll('*')) {
      if (e.matches(ignored) || getComputedStyle(e).display === 'none') continue;
      const rect = e.getBoundingClientRect();
      if (!rect.width || !rect.height) continue;
      const range = document.createRange();
      range.selectNodeContents(e);
      // 内联文字的内容矩形能发现 fixed 表格内溢出的 nowrap 单元格。
      const content = e.childElementCount || getComputedStyle(e).overflowX === 'hidden' ? rect : range.getBoundingClientRect();
      const right = Math.max(rect.right, content.right);
      const left = Math.min(rect.left, content.left);
      if (right > body.right + 1 || left < body.left - 1) {
        overflow.push({tag:e.tagName, cls:e.className, text:e.textContent.trim().slice(0,80),
          width_px:rect.width, right_px:right - body.left});
      }
    }
    const body_pt = parseFloat(getComputedStyle(document.body).fontSize) * 0.75;
    if (Math.abs(body_pt - 10.5) > 0.01) font_errors.push({text:'body', pt:body_pt});
    for (const p of document.querySelectorAll('p')) {
      if (p.closest('figure,aside,.toc,.appendix,.disclaimer-page') || p.matches('.small,.note,.src')) continue;
      if (p.textContent.trim().length < 20) continue;
      const pt = parseFloat(getComputedStyle(p).fontSize) * 0.75;
      if (Math.abs(pt - 10.5) > 0.01) font_errors.push({text:p.textContent.slice(0,60), pt});
      const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const text = walker.currentNode.textContent.replace(/\s/g,'');
        if (text.length >= 24 && samples.length < 8) samples.push({text:text.slice(0,32), expected_pt:10.5});
      }
    }
    const broken_images = [...document.images].filter(i => !i.naturalWidth).map(i => i.getAttribute('src'));
    output.textContent = JSON.stringify({body_pt, width_px:body.width, overflow:overflow.slice(0,30),
      font_errors, samples, broken_images});
  } catch (e) {
    output.textContent = JSON.stringify({error:String(e)});
  }
  document.body.append(output);
}, {once:true});
