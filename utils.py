from time import time

import aiohttp


def tCurrent():
    return int(time())


class ttapi:
    def __init__(self):
        self.url = "https://api-h2.tiktokv.com/aweme/v1/feed/?version_code=2613&aweme_id=7142788943921122566&device_type=Pixel%204"
        self.headers = {
            "user-agent": "Mozilla/5.0 (Linux; Android 8.0; Pixel 2 Build/OPD3.170816.012)"
            "AppleWebKit/537.36 (KHTML, like Gecko)"
            "Chrome/87.0.4280.88 Mobile Safari/537.36 Edg/87.0.664.66"}

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
                    res["aweme_list"][0]["video"]["play_addr"]["url_list"][2],
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
