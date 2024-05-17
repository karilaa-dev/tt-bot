import re

import aiohttp

from data.config import rapid_api


class ttapi:
    def __init__(self):
        self.url = 'https://api22-normal-c-alisg.tiktokv.com/aweme/v1/feed/'
        self.params = {"pull_type": 4, "interest_list": "{\"special_type\":0,\"recommend_group\":1}",
                       "iid": "7318518857994389254",
                       "device_id": "7318517321748022790",
                       "channel": "googleplay",
                       "app_name": "musical_ly",
                       "version_code": "300904",
                       "device_platform": "android",
                       "device_type": "ASUS_Z01QD",
                       "os_version": "9"}
        self.redirect_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')
        self.mobile_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+')
        self.web_regex = re.compile(r'https?:\/\/www.tiktok.com\/@[^\s]+?\/video\/[0-9]+')
        self.mus_regex = re.compile(r'https?://www.tiktok.com/music/[^\s]+')

    async def get_id_from_mobile(self, link: str):
        async with aiohttp.ClientSession() as client:
            async with client.get(link) as response:
                url = response.url
        return url.name

    async def regex_check(self, link: str):
        if self.web_regex.search(link) is not None:
            link = self.web_regex.findall(link)[0]
            return link, False
        elif self.mobile_regex.search(link) is not None:
            link = self.mobile_regex.findall(link)[0]
            return link, True
        else:
            return None, None

    async def get_id(self, link: str, is_mobile: bool):
        video_id = None
        if not is_mobile:
            video_id = self.redirect_regex.findall(link)[0]
        elif is_mobile:
            try:
                video_id = await self.get_id_from_mobile(link)
            except:
                pass
        return video_id

    async def get_video_data(self, video_id: int):
        async with aiohttp.ClientSession() as client:
            self.params['aweme_id'] = video_id
            async with client.get(self.url, params=self.params) as response:
                try:
                    res = await response.json()
                except:
                    return None

        if res is None or res['status_code'] != 0:
            return None
        elif res['aweme_list'][0]['aweme_id'] != str(video_id):
            return False
        return res['aweme_list'][0]

    async def rapid_get_video_data(self, link):
        url = "https://tokapi-mobile-version.p.rapidapi.com/v1/post"
        headers = {
            "X-RapidAPI-Key": rapid_api,
            "X-RapidAPI-Host": "tokapi-mobile-version.p.rapidapi.com"
        }
        querystring = {"video_url": link}
        async with aiohttp.ClientSession(headers=headers) as client:
            async with client.get(url, params=querystring) as response:
                try:
                    res = await response.json()
                except:
                    return None
            if 'error' in res:
                return False
            else:
                return res['aweme_detail']

    async def rapid_get_video_data_id(self, video_id: int):
        url = "https://tokapi-mobile-version.p.rapidapi.com/v1/post"+'/'+str(video_id)
        headers = {
            "X-RapidAPI-Key": rapid_api,
            "X-RapidAPI-Host": "tokapi-mobile-version.p.rapidapi.com"
        }
        async with aiohttp.ClientSession(headers=headers) as client:
            async with client.get(url) as response:
                try:
                    res = await response.json()
                except:
                    return None
            if 'error' in res:
                return False
            else:
                return res['aweme_detail']

    async def video(self, video_id: int):
        video_info = await self.get_video_data(video_id)
        if video_info is None:
            return None
        elif video_info is False:
            return False
        if video_info['aweme_type'] == 150:
            video_type = 'images'
            video_data = []
            for image in video_info['image_post_info']['images']:
                video_data.append(image["display_image"]["url_list"][1])
        else:
            video_type = 'video'
            video_data = video_info['video']['play_addr']['url_list'][0]
        return {
            'type': video_type,
            'data': video_data,
            'id': video_id,
            'cover': video_info['video']['origin_cover'][
                'url_list'][0],
            'width': video_info['video']['play_addr']['width'],
            'height': video_info['video']['play_addr'][
                'height'],
            'duration': video_info['video']['duration'],
            'author': video_info['author']['unique_id'],
        }

    async def rapid_video(self, video_link: str):
        video_info = await self.rapid_get_video_data(video_link)
        if video_info is None:
            return None
        elif video_info is False:
            return False
        if video_info['aweme_type'] == 150:
            video_type = 'images'
            video_data = []
            for image in video_info['image_post_info']['images']:
                video_data.append(image["display_image"]["url_list"][0])
        else:
            video_type = 'video'
            video_data = video_info['video']['play_addr_h264']['url_list'][0]
        return {
            'type': video_type,
            'data': video_data,
            'id': video_info['aweme_id'],
            'cover': video_info['video']['origin_cover']['url_list'][0],
            'width': video_info['video']['width'],
            'height': video_info['video']['height'],
            'duration': video_info['video']['duration'],
            'author': video_info['author']['unique_id'],
        }

    async def music(self, video_id: int):
        video_info = await self.get_video_data(video_id)
        if video_info is None:
            return None
        elif video_info is False:
            return False
        return {
            'data': video_info['music']['play_url']['uri'],
            'id': video_id,
            'title': video_info['music']['title'],
            'author': video_info['music']['author'],
            'duration': video_info['music']['duration'],
            'cover':
                video_info['music']['cover_large']['url_list'][0]
        }

    async def rapid_music(self, video_id: str):
        video_info = await self.rapid_get_video_data_id(video_id)
        if video_info is None:
            return None
        elif video_info is False:
            return False
        return {
            'data': video_info['music']['play_url']['uri'],
            'id': video_info['aweme_id'],
            'title': video_info['music']['title'],
            'author': video_info['music']['author'],
            'duration': video_info['music']['duration'],
            'cover':
                video_info['music']['cover_large']['url_list'][0]
        }