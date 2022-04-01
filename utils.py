from time import time

import aiosonic
from simplejson import loads as jloads


def tCurrent():
    return int(time())


class ttapi:
    def __init__(self, api_key: str):
        self.url = "https://tiktok-video-no-watermark2.p.rapidapi.com/"
        self.free_url = "https://api-va.tiktokv.com/aweme/v1/multi/aweme/detail/?aweme_ids=[{}]"
        self.headers = {
            'x-rapidapi-host': "tiktok-video-no-watermark2.p.rapidapi.com",
            'x-rapidapi-key': api_key
        }

    async def url_free(self, id: int):
        try:
            async with aiosonic.HTTPClient() as client:
                req = await client.post(self.free_url.format(id))
            try:
                res = jloads(await req.content())
            except:
                return 'connerror'
            if res['status_code'] != 0: return 'errorlink'
            return {
                'url': res['aweme_details'][0]['video']['play_addr']['url_list'][0],
                'id': id,
                'cover': res['aweme_details'][0]['video']['origin_cover']['url_list'][0],
                'width': res['aweme_details'][0]['video']['play_addr']['width'],
                'height': res['aweme_details'][0]['video']['play_addr']['height'],
                'duration': res['aweme_details'][0]['video']['duration']
            }
        except:
            return 'error'

    async def url_paid(self, link: str):
        querystring = {"url": f"{link}", "hd": "0"}
        try:
            client = aiosonic.HTTPClient()
            req = await client.post(self.url, headers=self.headers, data=querystring)
            try:
                res = jloads(await req.content())
            except:
                return 'connerror'
            if res['code'] == -1: return 'errorlink'
            return {
                'url': res['data']['play'],
                'id': res['data']['music_info']['id'],
                'cover': res['data']['origin_cover'],
                'width': 720,
                'height': 1280,
                'duration': 0
            }
        except:
            return 'error'

    async def url_free_music(self, id: int):
        try:
            async with aiosonic.HTTPClient() as client:
                req = await client.post(self.free_url.format(id))
            try:
                res = jloads(await req.content())
            except:
                return 'connerror'
            if res['status_code'] != 0: return 'errorlink'
            return {
                'url': res['aweme_details'][0]['music']['play_url']['uri'],
                'title': res['aweme_details'][0]['music']['title'],
                'author': res['aweme_details'][0]['music']['author'],
                'duration': res['aweme_details'][0]['music']['duration'],
                'cover': res['aweme_details'][0]['music']['cover_large']['url_list'][0]
            }
        except:
            return 'error'

    async def url_paid_music(self, link: str):
        querystring = {"url": f"{link}"}
        try:
            client = aiosonic.HTTPClient()
            req = await client.post(self.url + 'music/info', headers=self.headers, data=querystring)
            try:
                res = jloads(await req.content())
            except:
                return 'connerror'
            if res['code'] == -1: return 'errorlink'
            return {
                'url': res['data']['play'],
                'title': res['data']['title'],
                'author': res['data']['author'],
                'duration': res['data']['duration'],
                'cover': res['data']['cover']
            }
        except:
            return 'error'
