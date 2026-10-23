// Generate accessible HTML companions. Requires Node.js and the marked package.
// SPDX-License-Identifier: GPL-3.0-only
const fs = require('node:fs');
const path = require('node:path');
const { marked } = require('marked');
const directory = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, 'doc');
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const plain = text => text.replace(/<[^>]*>/g, '').replace(/&[^;]+;/g, ' ');
const style = `
:root { color-scheme: light dark; font: 120%/1.65 system-ui, sans-serif; }
body { max-width: 76ch; margin: auto; padding: 1rem; }
a { text-decoration: underline; text-underline-offset: .15em; }
a:focus-visible { outline: .2rem solid currentColor; outline-offset: .2rem; }
pre { padding: 1rem; border: 1px solid; white-space: pre-wrap; overflow-wrap: anywhere; }
code { font-size: 1em; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid; padding: .5rem; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
h1, h2, h3, h4 { line-height: 1.3; }
@media print { nav, .skip { display: none; } body { max-width: none; } }
`;
function page(title, content, navigation) {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escape(title)} — YAC documentation</title><style>${style}</style></head>
<body><a class="skip" href="#main">Skip to main content</a>
${navigation}
<main id="main" tabindex="-1">${content}</main>
<footer><p>YAC documentation. <a href="index.html">All documents</a></p></footer>
</body></html>\n`;
}
const documents = [];
for (const filename of fs.readdirSync(directory).filter(name => name.endsWith('.md')).sort()) {
  const source = fs.readFileSync(path.join(directory, filename), 'utf8');
  const headings = [];
  let content = marked.parse(source, { gfm: true });
  content = content.replace(/<h([1-6])>([\s\S]*?)<\/h\1>/g, (_, level, label) => {
    const id = `section-${headings.length + 1}`;
    headings.push({ id, label, level: Number(level) });
    return `<h${level} id="${id}">${label}</h${level}>`;
  });
  // Only rewrite links to Markdown files that have a generated companion here.
  content = content.replace(/href="([^"#?]+)\.md(#[^"]*)?"/g, (original, target, fragment = '') => {
    if (/^[a-z]+:/i.test(target) || !fs.existsSync(path.resolve(directory, `${target}.md`))) return original;
    // Markdown sources currently have no fragment links; preserve any future fragment.
    return `href="${target}.html${fragment}"`;
  });
  content = content.replace(/<th>/g, '<th scope="col">');
  const title = headings.length ? plain(headings[0].label).trim() : filename;
  const sections = headings.filter(heading => heading.level > 1);
  const navigation = `<nav aria-label="Document navigation"><p><a href="index.html">All documents</a></p>${sections.length ?
    `<p>On this page:</p><ul>${sections.map(h => `<li><a href="#${h.id}">${h.label}</a></li>`).join('')}</ul>` : ''}</nav>`;
  const output = filename.replace(/\.md$/, '.html');
  fs.writeFileSync(path.join(directory, output), page(title, content, navigation));
  documents.push({ title, output });
}
const index = `<h1>YAC documentation</h1><p>Choose a document. Each page has heading navigation and a link back to this list.</p><ul>${documents.map(d =>
  `<li><a href="${d.output}">${escape(d.title)}</a></li>`).join('')}</ul>`;
fs.writeFileSync(path.join(directory, 'index.html'), page('Document index', index, '<nav aria-label="Document navigation"><p>Document index</p></nav>'));
console.log(`Generated ${documents.length} documents and doc/index.html.`);
