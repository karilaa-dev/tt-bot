from time import time
from typing import Optional

import aiohttp


def tCurrent():
    return int(time())


class ttapi:
    def __init__(self):
        self.url = "https://api-h2.tiktokv.com/aweme/v1/feed/?version_code=2613&aweme_id={}&device_type=Pixel%204"
        self.headers = {
            "user-agent": "Mozilla/5.0 (Linux; Android 8.0; Pixel 2 Build/OPD3.170816.012) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
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
                'cover': res['aweme_list'][0]['video']['origin_cover'][
                    'url_list'][
                    0],
                'width': res['aweme_list'][0]['video']['play_addr']['width'],
                'height': res['aweme_list'][0]['video']['play_addr'][
                    'height'],
                'duration': res['aweme_list'][0]['video']['duration']
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
                'url': res['aweme_list'][0]['music']['play_url']['uri'],
                'title': res['aweme_list'][0]['music']['title'],
                'author': res['aweme_list'][0]['music']['author'],
                'duration': res['aweme_list'][0]['music']['duration'],
                'cover':
                    res['aweme_list'][0]['music']['cover_large']['url_list'][
                        0]
            }
        except:
            return 'error'


class AsyncSession:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    # Вызов сессии
    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            new_session = aiohttp.ClientSession()
            self._session = new_session

        return self._session

    # Закрытие сессии
    async def close(self) -> None:
        if self._session is None:
            return None

        await self._session.close()
