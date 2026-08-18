/**
 * Landing SEO gate: JSON-LD parse + FAQ sync, required meta, no em dashes.
 * Used as seo-god.json build_cmd. Does not start a server.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(import.meta.dirname, "..");
const landing = path.join(root, "landing");
const EM_DASH = "\u2014";

export function extractFaqFromHtml(html) {
  const start = html.indexOf('class="faq"');
  if (start < 0) return [];
  const end = html.indexOf("</section>", start);
  const block = html.slice(start, end < 0 ? undefined : end);
  const re = /<summary>([\s\S]*?)<\/summary>\s*<p>([\s\S]*?)<\/p>/g;
  const items = [];
  let m;
  while ((m = re.exec(block))) {
    items.push({
      q: m[1].replace(/<[^>]+>/g, "").trim(),
      a: m[2].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim(),
    });
  }
  return items;
}

function parseLdBlocks(html) {
  const re = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g;
  const docs = [];
  let m;
  while ((m = re.exec(html))) {
    docs.push(JSON.parse(m[1]));
  }
  return docs;
}

function flattenLd(docs) {
  const nodes = [];
  for (const doc of docs) {
    if (doc && Array.isArray(doc["@graph"])) nodes.push(...doc["@graph"]);
    else if (doc) nodes.push(doc);
  }
  return nodes;
}

function scanEmDash(filePath, errors) {
  const text = fs.readFileSync(filePath, "utf8");
  const idx = text.indexOf(EM_DASH);
  if (idx >= 0) {
    const line = text.slice(0, idx).split("\n").length;
    errors.push(`${path.relative(root, filePath)}:${line} contains an em dash (U+2014)`);
  }
}

function extractHeadGtagConfig(html) {
  const headEnd = html.toLowerCase().indexOf("</head>");
  if (headEnd < 0) return null;
  const head = html.slice(0, headEnd);
  const loader = 'src="https://www.googletagmanager.com/gtag/js?id=G-88L32JZQDH"';
  if (!head.includes(loader)) return null;
  const after = head.slice(head.indexOf(loader));
  const start = after.indexOf("<script>");
  const end = after.indexOf("</script>", start);
  if (start < 0 || end < 0) return null;
  const body = after.slice(start + "<script>".length, end);
  if (!body.includes("G-88L32JZQDH") || !body.includes("gtag(")) return null;
  return body;
}

export function checkLandingSeo() {
  const errors = [];
  const indexPath = path.join(landing, "index.html");
  const html = fs.readFileSync(indexPath, "utf8");

  if (!html.includes('<link rel="canonical" href="https://baklog.app/"')) {
    errors.push("index.html missing canonical https://baklog.app/");
  }
  const descMatch = html.match(/<meta name="description" content="([^"]*)"/);
  if (!descMatch) {
    errors.push("index.html missing meta description");
  } else if (descMatch[1].length > 160) {
    errors.push(`index.html meta description is ${descMatch[1].length} chars (max 160)`);
  }
  if (!html.includes('property="og:image"')) {
    errors.push("index.html missing og:image");
  }
  if (!html.includes('rel="apple-touch-icon"')) {
    errors.push("index.html missing apple-touch-icon");
  }
  if (!html.includes('id="faq"')) {
    errors.push("index.html FAQ section missing id=faq");
  }

  let nodes = [];
  try {
    nodes = flattenLd(parseLdBlocks(html));
  } catch (err) {
    errors.push(`JSON-LD parse failed: ${err.message}`);
    return errors;
  }

  const types = new Set(nodes.map((n) => n && n["@type"]).filter(Boolean));
  for (const need of ["SoftwareApplication", "WebSite", "FAQPage"]) {
    if (!types.has(need)) errors.push(`JSON-LD missing @type ${need}`);
  }

  const faqPage = nodes.find((n) => n && n["@type"] === "FAQPage");
  const htmlFaq = extractFaqFromHtml(html);
  if (!htmlFaq.length) errors.push("no FAQ details/summary pairs in index.html");
  const ldQs = (faqPage?.mainEntity || []).map((e) => e?.name);
  if (ldQs.length !== htmlFaq.length) {
    errors.push(`FAQPage has ${ldQs.length} questions, HTML has ${htmlFaq.length}`);
  } else {
    htmlFaq.forEach((item, i) => {
      if (ldQs[i] !== item.q) {
        errors.push(`FAQ question ${i + 1} mismatch: JSON-LD ${JSON.stringify(ldQs[i])} vs HTML ${JSON.stringify(item.q)}`);
      }
    });
  }

  const gtagBody = extractHeadGtagConfig(html);
  if (!gtagBody) {
    errors.push("index.html <head> missing inline gtag config for G-88L32JZQDH");
  } else {
    const sha = crypto.createHash("sha256").update(gtagBody, "utf8").digest("base64");
    const token = `'sha256-${sha}'`;
    const vercel = fs.readFileSync(path.join(landing, "vercel.json"), "utf8");
    if (!vercel.includes(token)) {
      errors.push(`vercel.json CSP missing ${token} for the inline gtag snippet`);
    }
    if (!vercel.includes("https://www.googletagmanager.com")) {
      errors.push("vercel.json CSP missing googletagmanager.com for GA");
    }
  }

  const sitemap = fs.readFileSync(path.join(landing, "sitemap.xml"), "utf8");
  if (!sitemap.includes("<loc>https://baklog.app/</loc>")) {
    errors.push("sitemap.xml missing https://baklog.app/");
  }

  const robots = fs.readFileSync(path.join(landing, "robots.txt"), "utf8");
  if (!robots.includes("Disallow: /auth/")) {
    errors.push("robots.txt missing Disallow: /auth/");
  }
  if (!robots.includes("Sitemap: https://baklog.app/sitemap.xml")) {
    errors.push("robots.txt missing Sitemap URL");
  }

  const llms = path.join(landing, "llms.txt");
  if (!fs.existsSync(llms)) errors.push("landing/llms.txt missing");
  else scanEmDash(llms, errors);

  for (const name of fs.readdirSync(landing)) {
    if (name.endsWith(".html")) scanEmDash(path.join(landing, name), errors);
  }

  return errors;
}

if (path.resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  const errors = checkLandingSeo();
  if (errors.length) {
    console.error(`landing SEO check failed (${errors.length}):`);
    for (const e of errors) console.error(`  ${e}`);
    process.exit(1);
  }
  console.log("landing SEO check ok");
}
