import re
from random import randint

from httpx import AsyncClient, AsyncHTTPTransport

from data.loader import bot


class ttapi:
    def __init__(self):
        self.url = 'https://api16-normal-c-useast1a.tiktokv.com/aweme/v1/feed/?aweme_id={0}'
        self.headers = {
            'User-Agent': 'com.ss.android.ugc.trill/494+Mozilla/5.0+(Linux;+Android+12;+2112123G+Build/SKQ1.211006.001;+wv)+AppleWebKit/537.36+(KHTML,+like+Gecko)+Version/4.0+Chrome/107.0.5304.105+Mobile+Safari/537.36'
        }
        self.redirect_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')
        self.mobile_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+')
        self.web_regex = re.compile(r'https?:\/\/www.tiktok.com\/@[^\s]+?\/video\/[0-9]+')
        self.mus_regex = re.compile(r'https?://www.tiktok.com/music/[^\s]+')

    async def get_id_from_mobile(self, link: str):

        async with AsyncClient(transport=AsyncHTTPTransport(retries=2)) as client:
            response = await client.get(link)
            url = (response.text)[9:-26]

        video_id = self.redirect_regex.findall(url)[0]
        return video_id

    async def get_id(self, link: str, chat_id=None):
        if self.web_regex.match(link) is not None:
            if chat_id is not None:
                await bot.send_chat_action(chat_id, 'upload_video')
            link = self.web_regex.findall(link)[0]
            video_id = self.redirect_regex.findall(link)[0]
            return video_id, link
        elif self.mobile_regex.match(link) is not None:
            if chat_id is not None:
                await bot.send_chat_action(chat_id, 'upload_video')
            link = self.mobile_regex.findall(link)[0]
            video_id = await self.get_id_from_mobile(link)
            return video_id, link
        else:
            return None, None

    async def get_video_data(self, video_id: int):

        async with AsyncClient(transport=AsyncHTTPTransport(retries=2)) as client:
            response = await client.get(self.url.format(video_id),
                                        headers=self.headers)
            try:
                res = response.json()
            except:
                return None

        if res is None or res['status_code'] != 0:
            return None
        elif res['aweme_list'][0]['aweme_id'] != str(video_id):
            return False
        return res

    async def video(self, video_id: int):
        res = await self.get_video_data(video_id)
        if res is None:
            return None
        elif res is False:
            return False
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
        elif res is False:
            return False
        return {
            'url': res['aweme_list'][0]['music']['play_url']['uri'],
            'title': res['aweme_list'][0]['music']['title'],
            'author': res['aweme_list'][0]['music']['author'],
            'duration': res['aweme_list'][0]['music']['duration'],
            'cover':
                res['aweme_list'][0]['music']['cover_large']['url_list'][0]
        }
