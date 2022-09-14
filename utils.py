from time import time

import aiohttp


def tCurrent():
    return int(time())


class ttapi:
    def __init__(self):
        self.url = "http://api.tiktokv.com/aweme/v1/aweme/detail/?aweme_id={}"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 9; ASUS_X00TD; Flow) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/359.0.0.288 Mobile Safari/537.36"}

    async def video(self, id: int):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url.format(id), headers=self.headers) as response:
                    try:
                        res = await response.json()
                    except:
                        return 'connerror'
            if res['status_code'] != 0:
                return 'errorlink'
            return {
                'url':
                    res['aweme_detail']['video']['play_addr']['url_list'][
                        0],
                'id': id,
                'cover': res['aweme_detail']['video']['origin_cover'][
                    'url_list'][
                    0],
                'width': res['aweme_detail']['video']['play_addr']['width'],
                'height': res['aweme_detail']['video']['play_addr'][
                    'height'],
                'duration': res['aweme_detail']['video']['duration']
            }
        except:
            return 'error'

    async def music(self, id: int):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url.format(id), headers=self.headers) as response:
                    try:
                        res = await response.json()
                    except:
                        return 'connerror'
            if res['status_code'] != 0:
                return 'errorlink'
            return {
                'url': res['aweme_detail']['music']['play_url']['uri'],
                'title': res['aweme_detail']['music']['title'],
                'author': res['aweme_detail']['music']['author'],
                'duration': res['aweme_detail']['music']['duration'],
                'cover':
                    res['aweme_detail']['music']['cover_large']['url_list'][
                        0]
            }
        except:
            return 'error'
