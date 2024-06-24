import json
import m3u8
import re
import requests
import time
from alive_progress import alive_bar

FORBIDDEN_CHARS = ('/', '\\', ':', '*', '?', '"', '<', '>', '|',)
TIMEOUT = 1
RETRY = 5
DATA_URL_TEMPLATE = r'https://rutube.ru/api/play/options/{}/?no_404=true&referer=https%253A%252F%252Frutube.ru&pver=v2'
YAPPY_URL_TEMPLATE = r'https://rutube.ru/pangolin/api/web/yappy/yappypage/?client=wdp&source=shorts&videoId={}'


class Rutube:
    _data_url = None
    _data = None
    _video_url = None
    _video_id = None
    _m3u8_url = None
    _m3u8_data = None
    _title = None
    _duration = None
    _playlist = None
    _type = 'video'

    def __init__(self, video_url, *args, **kwargs):
        self._video_url = video_url

        if self._check_url():
            if '/yappy/' in self._video_url:
                self._type = 'yappy'
                self._video_id = self._get_video_id()
            else:
                self._video_id = self._get_video_id()
                self._data_url = self._get_data_url()
                self._data = self._get_data()
                self._m3u8_url = self._get_m3u8_url()
                self._m3u8_data = self._get_m3u8_data()
                self._title = self._get_title()

    def _get_data_url(self):
        return DATA_URL_TEMPLATE.format(self._video_id)

    @property
    def params(self):
        return dict(
            video_id=self._video_id,
            video_url=self._video_url,
            title=self._title,
            duration=self._duration,
        )

    def _get_video_id(self):
        result = re.findall(rf'{self._type}\/([(\w+\d+)+]+)', self._video_url)
        if not result:
            raise Exception('Cannot get the video ID from URL')
        return result[0]

    def _get_data(self):
        r = requests.get(self._data_url)
        return json.loads(r.content)

    def _check_url(self):
        if requests.get(self._video_url).status_code != 200:
            raise Exception(f'{self._video_url} is unavailable')
        return True

    def _get_title(self):
        return self._clean_title(self._data.get('title')) or self._video_id

    @staticmethod
    def _clean_title(title):
        if not title:
            return title

        return ''.join(filter(lambda x: x not in FORBIDDEN_CHARS, title))

    @property
    def playlist(self):
        if not self._playlist:
            self._playlist = self._get_playlist()
        return self._playlist

    def _get_playlist(self):
        if self._type == 'yappy':
            return YappyPlaylist(self._video_id)
        return RutubePlaylist(self._m3u8_data, self.params)

    def _get_m3u8_url(self):
        return self._data['video_balancer']['m3u8']

    def _get_m3u8_data(self):
        r = requests.get(self._m3u8_url)
        return m3u8.loads(r.text)


class BasePlaylist:
    _playlist = dict()

    def __init__(self, *args, **kwargs):
        pass

    def __iter__(self):
        return iter(self._playlist)

    def __next__(self):
        for video in self._playlist:
            yield video

    def __repr__(self):
        return str(self._playlist)

    def __getitem__(self, i):
        return self._playlist[i]


class YappyPlaylist(BasePlaylist):
    _video_id = None

    def __init__(self, video_id, *args, **kwargs):
        self._video_id = video_id
        self._playlist[video_id] = YappyVideo(self._video_id, self._get_video_link())
        self._playlist = list(self._playlist.values())

    def _get_videos(self) -> list:
        r = requests.get(YAPPY_URL_TEMPLATE.format(self._video_id))
        if r.status_code != 200:
            raise Exception(f'Error code: {r and r.status_code}')

        results: list = r.json().get('results')
        if not results:
            raise Exception(f'No results found')

        return results

    def _get_video_link(self):
        return self._get_videos()[0].get('link')


class RutubePlaylist(BasePlaylist):
    _playlist = dict()

    def __init__(self, data, params, *args, **kwargs):
        for playlist in data.playlists:
            res = playlist.stream_info.resolution
            if res in self._playlist:
                self._playlist[res]._reserve_path = playlist.uri
            else:
                self._playlist[res] = RutubeVideo(playlist, data, params)

        self._playlist = list(self._playlist.values())

    def __iter__(self):
        return iter(self._playlist)

    def __next__(self):
        for video in self._playlist:
            yield video

    def __repr__(self):
        return str(self._playlist)

    def __getitem__(self, i):
        return self._playlist[i]


class YappyVideo:
    _id = None
    _link = None

    def __init__(self, video_id, link, *args, **kwargs):
        self._id = video_id
        self._link = link

    def __str__(self):
        return f'{self.title}'

    def __repr__(self):
        return str(self)

    @property
    def title(self):
        return f'{self._id}.mp4'

    def download(self):
        with alive_bar(2, title=self.title) as bar:
            r = requests.get(self._link)
            if r.status_code != 200:
                raise Exception(f'Error code: {r and r.status_code}')
            bar()
            with open(f'{self.title}', 'wb') as f:
                f.write(r.content)
            bar()


class RutubeVideo:
    _id = None
    _title = None
    _base_path = None
    _reserve_path = None
    _codecs = None
    _resolution = None
    _segment_urls = None
    _duration = None

    def __str__(self):
        return f'{self._title} ({self.resolution})'

    def __repr__(self):
        return f'{self._title} ({self.resolution})'

    def __init__(self, playlist, data, params, *args, **kwargs):
        self._id = params.get('video_id')
        self._title = params.get('title')
        self._duration = params.get('duration')
        self._base_path = playlist.uri
        self._resolution = playlist.stream_info.resolution
        self._codecs = playlist.stream_info.codecs
        self._segment_urls = self._get_segment_urls()

    @property
    def title(self):
        return self.__str__()

    def _get_segment_urls(self):
        r = requests.get(self._base_path)
        if r.status_code != 200:
            r = requests.get(self._reserve_path)

        data = m3u8.loads(r.text)
        return [segment['uri'] for segment in data.data['segments']]

    @property
    def resolution(self):
        return 'x'.join(map(str, self._resolution))

    @staticmethod
    def _make_segment_uri(base_uri, segment_uri):
        return f'{base_uri[:base_uri.index(".m3u8")]}/{segment_uri.split("/")[-1]}'

    @staticmethod
    def _get_segment_data(uri):
        r = None
        retry = RETRY
        while retry:
            r = requests.get(uri)
            if r.status_code == 200:
                return r
            retry -= 1
            time.sleep(TIMEOUT)
        raise Exception(f'Error code: {r and r.status_code}')

    def download(self):
        with alive_bar(len(self._segment_urls), title=self.title) as bar:
            with open(f'{self.title}.mp4', 'wb') as f:
                for uri in self._segment_urls:
                    r = self._get_segment_data(
                        self._make_segment_uri(self._reserve_path, uri)) or self._get_segment_data(
                        self._make_segment_uri(self._base_path, uri))
                    f.write(r.content)
                    bar()
