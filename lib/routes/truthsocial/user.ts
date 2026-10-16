import { Route } from '@/types';
import { parseDate } from '@/utils/parse-date';
import cache from '@/utils/cache';
import puppeteer from '@/utils/puppeteer';
import logger from '@/utils/logger';

const ORIGIN = 'https://truthsocial.com';
const API_BASE = `${ORIGIN}/api`;

export const route: Route = {
    path: '/user/:username/:routeParams?',
    categories: ['social-media'],
    example: '/truthsocial/user/realDonaldTrump',
    parameters: {
        username: 'Truth Social handle, without the leading `@`',
        routeParams: 'Extra params: `replies=1` include replies, `reblogs=0` exclude re-Truths',
    },
    features: {
        requireConfig: false,
        requirePuppeteer: true,
        antiCrawler: true,
        supportBT: false,
        supportPodcast: false,
        supportScihub: false,
    },
    radar: [
        {
            source: ['truthsocial.com/@:username'],
            target: '/user/:username',
        },
    ],
    name: 'User Timeline',
    maintainers: [],
    handler,
};

async function handler(ctx) {
    const { username } = ctx.req.param();
    const routeParams = new URLSearchParams(ctx.req.param('routeParams'));
    const includeReplies = routeParams.get('replies') === '1';
    const includeReblogs = routeParams.get('reblogs') !== '0';
    const limit = Number.parseInt(ctx.req.query('limit') ?? '20', 10);

    // A single browser session gets the Cloudflare clearance cookie + real TLS
    // fingerprint, then does same-origin fetches against the JSON API.
    const browser = await puppeteer();
    let account;
    let statuses;
    try {
        const page = await browser.newPage();
        await page.setRequestInterception(true);
        page.on('request', (request) => {
            // Block heavy assets — we only need HTML + XHR to clear Cloudflare.
            ['image', 'media', 'font', 'stylesheet'].includes(request.resourceType()) ? request.abort() : request.continue();
        });

        // Land on the profile so Cloudflare issues a clearance cookie for the origin.
        logger.http(`Requesting ${ORIGIN}/@${username}`);
        await page.goto(`${ORIGIN}/@${username}`, { waitUntil: 'domcontentloaded' });

        // From inside the page context, same-origin fetch carries the cf cookie.
        const apiFetch = (path) =>
            page.evaluate(async (url) => {
                const res = await fetch(url, { headers: { accept: 'application/json' }, credentials: 'include' });
                if (!res.ok) {
                    throw new Error(`${res.status}`);
                }
                return res.json();
            }, path);

        account = await cache.tryGet(`truthsocial:account:${username}`, () => apiFetch(`${API_BASE}/v1/accounts/lookup?acct=${encodeURIComponent(username)}`));

        const params = new URLSearchParams({ exclude_replies: String(!includeReplies), limit: String(limit) });
        statuses = await apiFetch(`${API_BASE}/v1/accounts/${account.id}/statuses?${params}`);
    } finally {
        browser.close();
    }

    const items = statuses
        .filter((status) => includeReblogs || !status.reblog)
        .map((status) => {
            const source = status.reblog ?? status;
            const isReblog = Boolean(status.reblog);

            const media = (source.media_attachments ?? [])
                .map((m) => {
                    if (m.type === 'image') {
                        return `<img src="${m.url}" referrerpolicy="no-referrer">`;
                    }
                    if (m.type === 'video' || m.type === 'gifv') {
                        return `<video src="${m.url}" controls poster="${m.preview_url ?? ''}"></video>`;
                    }
                    return '';
                })
                .join('');

            let description = source.content || '';
            if (source.card) {
                description += `<br><a href="${source.card.url}">${source.card.title || source.card.url}</a>`;
            }
            description += media;

            return {
                title: `${isReblog ? `Re-Truth @${source.account?.username}: ` : ''}${textTitle(source.content)}`,
                description,
                link: source.url || status.url,
                guid: status.uri || status.url,
                pubDate: parseDate(status.created_at),
                author: `@${source.account?.username ?? username}`,
                category: source.tags?.map((t) => t.name),
            };
        });

    return {
        title: `${account.display_name || account.username} (@${account.username}) - Truth Social`,
        link: account.url || `${ORIGIN}/@${username}`,
        description: account.note,
        image: account.avatar,
        item: items,
        allowEmpty: true,
    };
}

function textTitle(html: string): string {
    const text = (html || '')
        .replaceAll(/<[^>]+>/g, ' ')
        .replaceAll(/\s+/g, ' ')
        .trim();
    return text.length > 100 ? `${text.slice(0, 100)}…` : text || '(no text)';
}
