import re

import aiohttp

from data.config import rapid_api, api_link


class ttapi:
    def __init__(self):
        self.url = api_link + '/api/hybrid/video_data'
        self.rapid_link = 'https://tokapi-mobile-version.p.rapidapi.com/v1/post'
        self.rapid_headers = {
            "X-RapidAPI-Key": rapid_api,
            "X-RapidAPI-Host": "tokapi-mobile-version.p.rapidapi.com"
        }
        self.video_info_params = {'minimal': 'false'}
        self.mobile_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+')
        self.web_regex = re.compile(r'https?:\/\/www.tiktok.com\/@[^\s]+?\/video\/[0-9]+')
        self.mus_regex = re.compile(r'https?://www.tiktok.com/music/[^\s]+')

    async def regex_check(self, video_link: str):
        if self.web_regex.search(video_link) is not None:
            link = self.web_regex.findall(video_link)[0]
            return link, False
        elif self.mobile_regex.search(video_link) is not None:
            link = self.mobile_regex.findall(video_link)[0]
            return link, True
        else:
            return None, None

    async def get_video_data(self, video_link: str):
        async with aiohttp.ClientSession() as client:
            self.video_info_params['url'] = video_link
            async with client.get(self.url, params=self.video_info_params) as response:
                try:
                    res = await response.json()
                except:
                    return None
        if res is None or "code" not in res:
            return None
        return res['data']

    async def rapid_get_video_data(self, link):
        querystring = {"video_url": link}
        async with aiohttp.ClientSession(headers=self.rapid_headers) as client:
            async with client.get(self.rapid_link, params=querystring) as response:
                try:
                    res = await response.json()
                except:
                    return None
            if 'error' in res:
                return False
            else:
                return res['aweme_detail']

    async def rapid_get_video_data_id(self, video_id: int):
        url = f'{self.rapid_link}/{str(video_id)}'
        async with aiohttp.ClientSession(headers=self.rapid_headers) as client:
            async with client.get(url) as response:
                try:
                    res = await response.json()
                except:
                    return None
            if 'error' in res:
                return False
            else:
                return res['aweme_detail']

    async def video(self, video_link: str):
        video_info = await self.get_video_data(video_link)
        if video_info in [None, False]:
            return video_info
        if 'video' not in video_info:
            return None
        elif 'imagePost' in video_info:
            video_type = 'images'
            video_duration = None
            video_width, video_height = None, None
            video_cover = None
            video_data = []
            for image in video_info['imagePost']['images']:
                video_data.append(image["imageURL"]["urlList"][0])
        else:
            video_type = 'video'
            video_data = None
            video_duration = int(video_info['video']['duration'])
            video_width = int(video_info['video']['width'])
            video_height = int(video_info['video']['height'])
            video_cover = video_info['video']['cover']
        return {
            'type': video_type,
            'data': video_data,
            'id': int(video_info['id']),
            'cover': video_cover,
            'width': video_width,
            'height': video_height,
            'duration': video_duration,
            'author': video_info['author']['uniqueId'],
            'link': video_link
        }

    async def rapid_video(self, video_link: str):
        video_info = await self.rapid_get_video_data(video_link)
        if video_info in [None, False]:
            return video_info
        if 'aweme_detail' not in video_info:
            return None
        if video_info['aweme_type'] == 150:
            video_type = 'images'
            video_duration = None
            video_width, video_height = None, None
            video_cover = None
            video_data = []
            for image in video_info['image_post_info']['images']:
                video_data.append(image["display_image"]["url_list"][-1])
        else:
            video_type = 'video'
            video_duration = int(video_info['video']['duration'])
            video_width = int(video_info['video']['width'])
            video_height = int(video_info['video']['height'])
            video_cover = video_info['video']['cover']['url_list'][0]
            if 'play_addr_h264' in video_info['video']:
                video_data = video_info['video']['play_addr_h264']['url_list'][0]
            else:
                video_data = video_info['video']['play_addr']['url_list'][0]
        return {
            'type': video_type,
            'data': video_data,
            'id': int(video_info['aweme_id']),
            'cover': video_cover,
            'width': video_width,
            'height': video_height,
            'duration': video_duration,
            'author': video_info['author']['unique_id'],
            'link': video_link
        }

    async def music(self, video_id):
        video_info = await self.get_video_data(f'https://www.tiktok.com/@ttgrab_bot/video/{video_id}')
        if video_info in [None, False]:
            return video_info
        if 'music' not in video_info:
            return None
        return {
            'data': video_info['music']['playUrl'],
            'id': int(video_info['id']),
            'title': video_info['music']['title'],
            'author': video_info['music']['authorName'],
            'duration': int(video_info['music']['duration']),
            'cover': video_info['music']['coverLarge']
        }

    async def rapid_music(self, video_id):
        video_info = await self.rapid_get_video_data_id(video_id)
        if video_info in [None, False]:
            return video_info
        return {
            'data': video_info['music']['play_url']['uri'],
            'id': video_info['aweme_id'],
            'title': video_info['music']['title'],
            'author': video_info['music']['author'],
            'duration': int(video_info['music']['duration']),
            'cover':
                video_info['music']['cover_large']['url_list'][0]
        }
