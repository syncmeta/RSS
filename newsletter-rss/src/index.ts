import PostalMime from "postal-mime";

interface Env {
  ITEMS: KVNamespace;
  // Optional: set with `wrangler secret put FEED_TOKEN` to make the feed private.
  FEED_TOKEN?: string;
}

// How many recent issues to include in the feed, and how long to keep them.
const MAX_ITEMS = 50;
const TTL_SECONDS = 60 * 60 * 24 * 365; // 1 year

interface StoredItem {
  title: string;
  from: string;
  to?: string;
  date: string; // ISO
  html: string;
  link?: string;
}

export default {
  // --- Inbound: Money Stuff (and any other newsletter) lands here ---
  async email(message, env, ctx): Promise<void> {
    const raw = await new Response(message.raw).arrayBuffer();
    const parsed = await PostalMime.parse(raw);

    const dateHeader = message.headers.get("date");
    const date = dateHeader ? new Date(dateHeader) : new Date();

    // Recipient localpart becomes the feed name, e.g. moneystuff@example.com -> "moneystuff".
    const box = (message.to.split("@")[0] || "inbox").toLowerCase().replace(/[^a-z0-9._-]/g, "");

    const item: StoredItem = {
      title: parsed.subject || "(no subject)",
      from: message.from,
      to: message.to,
      date: date.toISOString(),
      html: parsed.html || `<pre>${escapeHtml(parsed.text || "")}</pre>`,
    };

    // Key sorts newest-first within a box: item:<box>:<reverse-ts>:<rand>
    const reverse = (1e15 - date.getTime()).toString().padStart(16, "0");
    const key = `item:${box}:${reverse}:${crypto.randomUUID().slice(0, 8)}`;

    await env.ITEMS.put(key, JSON.stringify(item), { expirationTtl: TTL_SECONDS });
  },

  // --- Outbound: your RSS reader fetches the feed ---
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);

    // "/" or "/feed.xml" -> combined feed (all boxes).
    // "/feed/<box>.xml" -> only mail sent to <box>@yourdomain.
    let prefix = "item:";
    let title = "Newsletters (full text)";
    const m = url.pathname.match(/^\/feed\/([a-z0-9._-]+)\.xml$/);
    if (m) {
      prefix = `item:${m[1]}:`;
      title = `${m[1]} (full text)`;
    } else if (url.pathname !== "/feed.xml" && url.pathname !== "/") {
      return new Response("Not found", { status: 404 });
    }

    if (env.FEED_TOKEN && url.searchParams.get("token") !== env.FEED_TOKEN) {
      return new Response("Unauthorized", { status: 401 });
    }

    const list = await env.ITEMS.list({ prefix, limit: MAX_ITEMS });
    const items: StoredItem[] = [];
    for (const k of list.keys) {
      const v = await env.ITEMS.get(k.name);
      if (v) items.push(JSON.parse(v) as StoredItem);
    }

    const xml = buildRss(items, url.origin, title);
    return new Response(xml, {
      headers: { "content-type": "application/rss+xml; charset=utf-8" },
    });
  },
} satisfies ExportedHandler<Env>;

function buildRss(items: StoredItem[], origin: string, title: string): string {
  const entries = items
    .map(
      (it) => `    <item>
      <title>${escapeXml(it.title)}</title>
      <pubDate>${new Date(it.date).toUTCString()}</pubDate>
      <guid isPermaLink="false">${escapeXml(it.date + it.title)}</guid>
      <author>${escapeXml(it.from)}</author>
      <description><![CDATA[${it.html}]]></description>
    </item>`
    )
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>${escapeXml(title)}</title>
    <link>${origin}/feed.xml</link>
    <description>Newsletters delivered via Cloudflare Email Routing</description>
${entries}
  </channel>
</rss>`;
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (c) =>
    ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]!)
  );
}

function escapeHtml(s: string): string {
  return s.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]!));
}
