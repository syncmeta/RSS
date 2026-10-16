import { createHash } from 'node:crypto';

import { load } from 'cheerio';

import type { Data, DataItem, Route } from '@/types';
import { ViewType } from '@/types';
import cache from '@/utils/cache';
import ofetch from '@/utils/ofetch';
import logger from '@/utils/logger';
import { parseDate } from '@/utils/parse-date';
import parser from '@/utils/rss-parser';

// The `nyt-token` is a static public key shipped to every NYT web client. It rotates
// occasionally; override with the NYT_TOKEN env var when it does.
const NYT_TOKEN =
    process.env.NYT_TOKEN ||
    'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAs+/oUCTBmD/cLdmcecrnBMHiU/pxQCn2DDyaPKUOXxi4p0uUSZQzsuq1pJ1m5z1i0YGPd1U1OeGHAChWtqoxC7bFMCXcwnE1oyui9G1uobgpm1GdhtwkR7ta7akVTcsF8zxiXx7DNXIPd2nIJFH83rmkZueKrC4JVaNzjvD+Z03piLn5bHWU6+w+rA+kyJtGgZNTXKyPh6EC6o5N+rknNMG5+CdTq35p8f99WjFawSvYgP9V64kgckbTbtdJ6YhVP58TnuYgr12urtwnIqWP9KSJ1e5vmgf3tunMqWNm6+AnsqNj8mCLdCuc5cEB74CwUeQcP2HQQmbCddBy2y0mEwIDAQAB';

const SAMIZDAT = 'https://samizdat-graphql.nytimes.com/graphql/v2';

interface Section {
    title: string;
    source: 'rss' | 'page';
    url: string;
    link?: string;
}

const sections: Record<string, Section> = {
    homepage: { title: 'Home Page', source: 'rss', url: 'https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml' },
    magazine: { title: 'NYT Magazine', source: 'rss', url: 'https://rss.nytimes.com/services/xml/rss/nyt/Magazine.xml' },
    theupshot: { title: 'The Upshot', source: 'rss', url: 'https://rss.nytimes.com/services/xml/rss/nyt/Upshot.xml' },
    dealbook: { title: 'DealBook', source: 'rss', url: 'https://rss.nytimes.com/services/xml/rss/nyt/DealBook.xml' },
    'visual-investigations': { title: 'Visual Investigations', source: 'rss', url: 'https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/spotlight/visual-investigations/rss.xml', link: 'https://www.nytimes.com/spotlight/visual-investigations' },
};

// Fetch a single article's full text from NYT's samizdat GraphQL gateway (Varnish,
// no DataDome). Uses open Automatic Persisted Queries: we supply our own query text
// plus its sha256, so we never depend on NYT's rotating persisted-query hashes.
async function fetchArticle(url: string): Promise<{ headline?: string; author?: string; pubDate?: string; html?: string } | null> {
    const query = `query{article(id:"${url}"){__typename ... on Article{headline{default} summary firstPublished bylines{renderedRepresentation} body{content{__typename ... on ParagraphBlock{content{__typename ... on TextInline{text}}} ... on HeaderBasicBlock{headline{__typename ... on Heading2Block{content{__typename ... on TextInline{text}}} ... on Heading3Block{content{__typename ... on TextInline{text}}}}} ... on ImageBlock{media{__typename ... on Image{caption{text} crops(renditionNames:["articleLarge"]){renditions{url}}}}}}}}}}`;
    const sha256Hash = createHash('sha256').update(query).digest('hex');

    let data;
    try {
        data = await ofetch(SAMIZDAT, {
            method: 'POST',
            headers: {
                'content-type': 'application/json',
                'nyt-token': NYT_TOKEN,
                'nyt-app-type': 'project-vi',
                'nyt-app-version': '0.0.5',
                origin: 'https://www.nytimes.com',
                referer: 'https://www.nytimes.com/',
                cookie: process.env.NYT_S_COOKIE || '',
            },
            body: { query, extensions: { persistedQuery: { version: 1, sha256Hash } } },
        });
    } catch (error) {
        logger.warn(`nytimes fulltext: samizdat request failed for ${url}: ${error}`);
        return null;
    }

    const article = data?.data?.article;
    if (!article || article.__typename !== 'Article') {
        return null;
    }

    const textOf = (block) => (block?.content ?? []).filter((n) => n.__typename === 'TextInline').map((n) => n.text).join('');

    const parts: string[] = [];
    for (const block of article.body?.content ?? []) {
        switch (block.__typename) {
            case 'ParagraphBlock': {
                const t = textOf(block);
                if (t) {
                    parts.push(`<p>${t}</p>`);
                }
                break;
            }
            case 'HeaderBasicBlock': {
                const t = textOf(block.headline);
                if (t) {
                    parts.push(`<h2>${t}</h2>`);
                }
                break;
            }
            case 'ImageBlock': {
                const media = block.media;
                const src = media?.crops?.[0]?.renditions?.[0]?.url;
                if (src) {
                    const caption = media?.caption?.text ?? '';
                    parts.push(`<figure><img src="${src}">${caption ? `<figcaption>${caption}</figcaption>` : ''}</figure>`);
                }
                break;
            }
            default:
                break;
        }
    }

    return {
        headline: article.headline?.default,
        author: (article.bylines ?? []).map((b) => b.renderedRepresentation).join('; ') || undefined,
        pubDate: article.firstPublished,
        html: parts.join(''),
    };
}

async function handler(ctx): Promise<Data> {
    const key = (ctx.req.param('section') || '').toLowerCase();
    const section = sections[key];
    if (!section) {
        throw new Error(`Unknown NYT section "${key}". Available: ${Object.keys(sections).join(', ')}`);
    }
    const limit = Number.parseInt(ctx.req.query('limit') ?? '15', 10) || 15;

    // Step 1: collect candidate article URLs (+ any metadata the source gives us).
    let candidates: { url: string; title?: string; pubDate?: string; author?: string }[] = [];
    if (section.source === 'rss') {
        const feed = await parser.parseURL(section.url);
        candidates = feed.items.map((item) => ({
            url: (item.link || '').split('?')[0],
            title: item.title,
            pubDate: item.pubDate,
            author: item.creator || item['dc:creator'],
        }));
    } else {
        const html = await ofetch(section.url);
        const $ = load(html);
        const seen = new Set<string>();
        $('a[href]').each((_, el) => {
            const href = $(el).attr('href') || '';
            const m = href.match(/^(?:https:\/\/www\.nytimes\.com)?(\/\d{4}\/\d{2}\/\d{2}\/[^?#"]+\.html)/);
            if (m) {
                const full = `https://www.nytimes.com${m[1]}`;
                if (!seen.has(full)) {
                    seen.add(full);
                    candidates.push({ url: full });
                }
            }
        });
    }

    candidates = candidates.filter((c) => c.url).slice(0, limit);

    // Step 2: fetch full text per article (cached). Cache the article object (never
    // null, so the tryGet return type stays a Record) and build the item afterwards.
    const items = (
        await Promise.all(
            candidates.map(async (c) => {
                const article = (await cache.tryGet(`nytimes:fulltext:${c.url}`, async () => (await fetchArticle(c.url)) ?? {})) as {
                    headline?: string;
                    author?: string;
                    pubDate?: string;
                    html?: string;
                };
                if (!article?.html) {
                    return null;
                }
                return {
                    title: c.title || article.headline || c.url,
                    link: c.url,
                    description: article.html,
                    author: c.author || article.author,
                    pubDate: parseDate(c.pubDate || article.pubDate || ''),
                } as DataItem;
            })
        )
    ).filter((item): item is DataItem => Boolean(item));

    return {
        title: `NYT · ${section.title} (full text)`,
        link: section.link || (section.source === 'page' ? section.url : 'https://www.nytimes.com'),
        description: `The New York Times ${section.title} — full-text articles`,
        item: items,
    };
}

export const route: Route = {
    path: '/fulltext/:section',
    categories: ['traditional-media'],
    view: ViewType.Articles,
    example: '/nytimes/fulltext/magazine',
    parameters: {
        section: {
            description: 'NYT section',
            options: Object.entries(sections).map(([value, s]) => ({ value, label: s.title })),
        },
    },
    features: {
        requireConfig: [
            { name: 'NYT_S_COOKIE', optional: false, description: 'NYT subscriber cookie (at least the `NYT-S=...` value) used to unlock paywalled full text via the samizdat GraphQL gateway.' },
            { name: 'NYT_TOKEN', optional: true, description: "NYT web `nyt-token` header; only needed if the built-in default stops working." },
        ],
        requirePuppeteer: false,
        antiCrawler: false,
        supportBT: false,
        supportPodcast: false,
        supportScihub: false,
    },
    name: 'Full-text sections',
    maintainers: [],
    handler,
    description: `Full-text NYT section feeds. Fetches article URLs from official section RSS (or the section page) and pulls paywalled full text via NYT's samizdat GraphQL gateway, bypassing DataDome. Requires an NYT subscriber cookie in \`NYT_S_COOKIE\`.

Available sections: ${Object.keys(sections)
        .map((s) => `\`${s}\``)
        .join(', ')}.`,
};
