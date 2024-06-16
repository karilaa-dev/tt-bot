import re

import aiohttp

redirect_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')

async def get_id_from_mobile(link: str):
    async with aiohttp.ClientSession() as client:
        async with client.get(link) as response:
            url = response.url
    return url.name


async def get_id(link: str, is_mobile: bool):
    video_id = None
    if not is_mobile:
        video_id = redirect_regex.findall(link)[0]
    elif is_mobile:
        try:
            video_id = await get_id_from_mobile(link)
        except:
            pass
    return video_id
