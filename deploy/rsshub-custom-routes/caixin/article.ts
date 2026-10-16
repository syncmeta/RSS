import type { Route } from '@/types';
import cache from '@/utils/cache';
import got from '@/utils/got';
import { parseDate } from '@/utils/parse-date';

import { parseArticle } from './utils';
import { getFulltext } from './utils-fulltext';

export const route: Route = {
    path: '/article',
    categories: ['traditional-media'],
    example: '/caixin/article',
    parameters: {},
    description: '订阅用户配置 `CAIXIN_COOKIE` 后，可在 url 传入 `?fulltext=true` 解锁正文全文。',
    features: {
        requireConfig: false,
        requirePuppeteer: false,
        antiCrawler: false,
        supportBT: false,
        supportPodcast: true,
        supportScihub: false,
    },
    radar: [
        {
            source: ['caixin.com/'],
        },
    ],
    name: '首页新闻',
    maintainers: ['EsuRt'],
    handler,
    url: 'caixin.com/',
};

async function handler(ctx) {
    const { data: response } = await got('https://mapiv5.caixin.com/m/api/getWapIndexListByPage');

    const list = response.data.list.map((item) => ({
        title: item.title,
        description: item.summary,
        author: item.author_name,
        pubDate: parseDate(item.time, 'X'),
        link: item.web_url,
        pics: item.pics,
        audio: item.cms_audio_url,
        audio_image_url: item.audio_image_url,
    }));

    const fulltext = ctx.req.query('fulltext') === 'true';
    const items = await Promise.all(
        list.map((item) =>
            // prefix the cache key so the full-text and preview variants don't collide
            cache.tryGet(`caixin:article:${fulltext ? 'full:' : ''}${item.link}`, async () => {
                const parsed = await parseArticle(item);
                if (fulltext) {
                    const authorizedFullText = await getFulltext(item.link);
                    if (authorizedFullText) {
                        parsed.description = authorizedFullText;
                    }
                }
                return parsed;
            })
        )
    );

    return {
        title: '财新网 - 首页',
        link: 'https://www.caixin.com',
        description: '财新网 - 首页',
        item: items,
    };
}
