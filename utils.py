from random import sample
from time import time
from typing import Optional

import aiohttp


def tCurrent():
    return int(time())


class ttapi:
    def __init__(self):
        self.url = 'https://api-h2.tiktokv.com/aweme/v1/feed/?aweme_id={}&version_name=26.1.3&version_code=2613&build_number=26.1.3&manifest_version_code=2613&update_version_code=2613&openudid={}&uuid={}&_rticket={}&ts={}&device_brand=Google&device_type=Pixel%204&device_platform=android&resolution=1080*1920&dpi=420&os_version=10&os_api=29&carrier_region=US&sys_region=US%C2%AEion=US&app_name=trill&app_language=en&language=en&timezone_name=America/New_York&timezone_offset=-14400&channel=googleplay&ac=wifi&mcc_mnc=310260&is_my_cn=0&aid=1180&ssmix=a&as=a1qwert123&cp=cbfhckdckkde1'
        self.headers = {
            'user-agent': 'com.ss.android.ugc.trill/2613 (Linux; U; Android 10; en_US; Pixel 4; Build/QQ3A.200805.001; Cronet/58.0.2991.0)'
        }

    async def video(self, id: int):
        try:
            openudid = ''.join(sample('0123456789abcdef', 16))
            uuid = ''.join(sample('01234567890123456', 16))
            ts = int(time())
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url.format(id, openudid, uuid, ts*1000, ts), headers=self.headers) as response:
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
