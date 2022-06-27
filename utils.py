from time import time

import aiosonic
from simplejson import loads as jloads


def tCurrent():
    return int(time())


class ttapi:
    def __init__(self):
        self.url = "https://api-va.tiktokv.com/aweme/v1/multi/aweme/detail/?aweme_ids=[{}]"

    async def video(self, id: int):
        try:
            async with aiosonic.HTTPClient() as client:
                req = await client.post(self.url.format(id))
            try:
                res = jloads(await req.content())
            except:
                return 'connerror'
            if res['status_code'] != 0:
                return 'errorlink'
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

    async def music(self, id: int):
        try:
            async with aiosonic.HTTPClient() as client:
                req = await client.post(self.url.format(id))
            try:
                res = jloads(await req.content())
            except:
                return 'connerror'
            if res['status_code'] != 0:
                return 'errorlink'
            return {
                'url': res['aweme_details'][0]['music']['play_url']['uri'],
                'title': res['aweme_details'][0]['music']['title'],
                'author': res['aweme_details'][0]['music']['author'],
                'duration': res['aweme_details'][0]['music']['duration'],
                'cover': res['aweme_details'][0]['music']['cover_large']['url_list'][0]
            }
        except:
            return 'error'
