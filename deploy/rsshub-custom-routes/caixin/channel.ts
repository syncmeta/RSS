import { load } from 'cheerio';

import InvalidParameterError from '@/errors/types/invalid-parameter';
import type { Route } from '@/types';
import cache from '@/utils/cache';
import got from '@/utils/got';
import { parseDate } from '@/utils/parse-date';
import timezone from '@/utils/timezone';
import { isValidHost } from '@/utils/valid-host';

import { parseArticle } from './utils';
import { getFulltext } from './utils-fulltext';

export const route: Route = {
    path: '/channel/:column',
    categories: ['traditional-media'],
    example: '/caixin/channel/opinion',
    parameters: { column: '频道对应的子域名，如 `opinion`（观点）、`cnreform`（中国改革）' },
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
            source: ['opinion.caixin.com/', 'opinion.caixin.com/index.html'],
            target: '/channel/opinion',
        },
        {
            source: ['cnreform.caixin.com/', 'cnreform.caixin.com/index.html'],
            target: '/channel/cnreform',
        },
        {
            source: ['bijiao.caixin.com/', 'bijiao.caixin.com/index.html'],
            target: '/channel/bijiao',
        },
    ],
    name: '频道',
    maintainers: ['idealclover'],
    handler,
    description: `抓取财新网频道首页（子域名）的最新文章，例如：

| 观点    | 中国改革 | 比较   |
| ------- | -------- | ------ |
| opinion | cnreform | bijiao |

订阅用户配置 \`CAIXIN_COOKIE\` 后，可在 url 传入 \`?fulltext=true\` 解锁正文全文。`,
};

async function handler(ctx) {
    const column = ctx.req.param('column');
    if (!isValidHost(column)) {
        throw new InvalidParameterError('Invalid column');
    }

    const url = `https://${column}.caixin.com`;
    const response = await got(url);
    const $ = load(response.data);
    const title = $('head title').text();

    // entity 对象在不同频道间字段顺序不一，且可能包含 `"propData":"{}"` 这类嵌套花括号，
    // 直接 JSON.parse 不稳健，这里只提取频道 id。
    const id = response.data.match(/var entity = \{[^}]*?"id":(\d+)/)?.[1];
    if (!id) {
        throw new InvalidParameterError('Cannot resolve channel id');
    }

    const {
        data: { datas: data },
    } = await got('https://gateway.caixin.com/api/extapi/homeInterface.jsp', {
        searchParams: {
            subject: id,
            type: 0,
            count: ctx.req.query('limit') ? Number.parseInt(ctx.req.query('limit')) : 25,
            picdim: '_266_177',
            start: 0,
        },
    });

    const list = data.map((item) => ({
        title: item.desc,
        description: item.summ,
        link: item.link.replace('http://', 'https://'),
        pubDate: timezone(parseDate(item.time), 8),
        category: item.keyword ? item.keyword.split(' ') : [],
        audio: item.audioUrl,
        audio_image_url: item.pict?.imgs?.[0]?.url,
    }));

    const fulltext = ctx.req.query('fulltext') === 'true';
    const items = await Promise.all(
        list.map((item) =>
            cache.tryGet(`caixin:channel:${fulltext ? 'full:' : ''}${item.link}`, async () => {
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
        title,
        link: url,
        description: '财新网 - 提供财经新闻及资讯服务',
        item: items,
    };
}
