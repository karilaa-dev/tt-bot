import re

import aiohttp


class ttapi:
    def __init__(self):
        self.url = 'https://api-h2.tiktokv.com/aweme/v1/feed/?aweme_id={0}&version_code=2613&aid=1180'
        self.headers = {
            'User-Agent': 'com.ss.android.ugc.trill/2613 (Linux; U; Android 10; en_US; Pixel 4; Build/QQ3A.200805.001; Cronet/58.0.2991.0)'
        }
        self.connector = aiohttp.TCPConnector(force_close=True)
        self.redirect_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')

    async def get_id_from_mobile(self, link: str):
        redirect_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(link, headers=self.headers) as response:
                url = str(response.url)
        video_id = self.redirect_regex.findall(url)[0]
        return video_id

    async def get_id(self, link: str):
        web_regex = re.compile(r'https?:\/\/www.tiktok.com\/@[^\s]+?\/video\/[0-9]+')
        mus_regex = re.compile(r'https?://www.tiktok.com/music/[^\s]+')
        mobile_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+')
        redirect_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')
        if web_regex.match(link) is not None:
            link = web_regex.findall(link)[0]
            video_id = redirect_regex.findall(link)[0]
            return video_id, link
        elif mobile_regex.match(link) is not None:
            link = mobile_regex.findall(link)[0]
            video_id = await self.get_id_from_mobile(link)
            return video_id, link
        else:
            return None, None

    async def get_video_data(self, video_id: int):
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(self.url.format(video_id), headers=self.headers) as response:
                try:
                    res = await response.json()
                except:
                    return None
        if res['status_code'] != 0:
            return None
        return res

    async def video(self, video_id: int):
        res = await self.get_video_data(video_id)
        if res is None:
            return None
        return {
            'url':
                res["aweme_list"][0]["video"]["play_addr"]["url_list"][2],
            'id': video_id,
            'cover': res['aweme_list'][0]['video']['origin_cover'][
                'url_list'][0],
            'width': res['aweme_list'][0]['video']['play_addr']['width'],
            'height': res['aweme_list'][0]['video']['play_addr'][
                'height'],
            'duration': res['aweme_list'][0]['video']['duration']
        }

    async def music(self, video_id: int):
        res = await self.get_video_data(video_id)
        if res is None:
            return None
        return {
            'url': res['aweme_list'][0]['music']['play_url']['uri'],
            'title': res['aweme_list'][0]['music']['title'],
            'author': res['aweme_list'][0]['music']['author'],
            'duration': res['aweme_list'][0]['music']['duration'],
            'cover':
                res['aweme_list'][0]['music']['cover_large']['url_list'][0]
        }
