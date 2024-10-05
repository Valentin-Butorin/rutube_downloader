import abc
import enum
import json
import m3u8
import re
import requests
import time
from alive_progress import alive_bar
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from pathlib import Path
from threading import Thread
from typing import Optional, BinaryIO, Text, List, Union
import sys

FORBIDDEN_CHARS = ('/', '\\', ':', '*', '?', '"', '<', '>', '|',)
TIMEOUT = 1
RETRY = 5
DATA_URL_TEMPLATE = r'https://rutube.ru/api/play/options/{}/?no_404=true&referer=https%253A%252F%252Frutube.ru&pver=v2'
YAPPY_URL_TEMPLATE = r'https://rutube.ru/pangolin/api/web/yappy/yappypage/?client=wdp&source=shorts&videoId={}'


class VideoType(enum.Enum):
    VIDEO = 'video'
    SHORTS = 'shorts'
    YAPPY = 'yappy'


class VideoAbstract(abc.ABC):
    @abc.abstractproperty
    def title(self):
        ...

    @abc.abstractproperty
    def resolution(self):
        ...

    @abc.abstractmethod
    def _write(self, stream: Optional[BinaryIO] = None, *args, **kwargs):
        ...

    def _build_file_path(self, path: Text = None) -> str:
        filename = f'{self.title}.mp4'
        if not path:
            return filename

        target_path = Path(path.rstrip('/').rstrip('\\')).resolve()
        if not target_path.exists():
            target_path.mkdir(parents=True, exist_ok=True)
        return target_path / filename

    def download(
            self,
            path: Optional[Text] = None,
            stream: Optional[BinaryIO] = None,
            workers: int = 0,
            *args,
            **kwargs
    ):
        if stream:
            self._write(stream, workers=workers * args, **kwargs)
        else:
            with open(self._build_file_path(path), 'wb') as file:
                self._write(file, workers=workers, *args, **kwargs)


class RutubeVideo(VideoAbstract):
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

    @property
    def title(self):
        return self.__str__()

    def _get_segment_urls(self):
        if self._segment_urls:
            return self._segment_urls

        r = requests.get(self._base_path)
        if r.status_code != 200:
            r = requests.get(self._reserve_path)
            if r.status_code != 200:
                raise Exception(f'Cannot get segments. Status code: {r.status_code}')

        data = m3u8.loads(r.text)
        self._segment_urls = [segment['uri'] for segment in data.data['segments']]
        return self._segment_urls

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

    def _get_segment_content(self, *args):
        uri, bar = args[0]
        r = (
                self._get_segment_data(self._make_segment_uri(self._reserve_path, uri))
                or self._get_segment_data(self._make_segment_uri(self._base_path, uri))
        )
        bar()
        return r.content

    @staticmethod
    def _write_from_deque(deq, stream, flag):
        while True:
            if deq:
                stream.write(deq.popleft())
            if flag:
                break

    def _write_threads(self, bar, stream: Optional[BinaryIO], workers: int = 0):
        deq = deque(maxlen=sys.maxsize)
        flag = []
        writer = Thread(target=self._write_from_deque, args=(deq, stream, flag), daemon=True)
        writer.start()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for content in pool.map(
                    self._get_segment_content,
                    [(uri, bar) for uri in self._get_segment_urls()]
            ):
                deq.append(content)
            else:
                flag.append(True)
                writer.join()

    def _write(self, stream: Optional[BinaryIO], workers: int = 0, *args, **kwargs):
        with alive_bar(len(self._get_segment_urls()), title=self.title) as bar:
            if workers:
                self._write_threads(bar, stream, workers)
            else:
                for uri in self._get_segment_urls():
                    stream.write(
                        self._get_segment_content((uri, bar))
                    )


class YappyVideo(VideoAbstract):
    _id = None
    _link = None
    _resolution = (1920, 1080)

    def __init__(self, video_id, link, *args, **kwargs):
        self._id = video_id
        self._link = link

    def __str__(self):
        return f'{self.title}'

    def __repr__(self):
        return str(self)

    @property
    def title(self):
        return self._id

    @property
    def resolution(self):
        return 'x'.join(map(str, self._resolution))

    def _write(self, stream: Optional[BinaryIO] = None, *args, **kwargs):
        with alive_bar(2, title=self.title) as bar:
            r = requests.get(self._link)
            if r.status_code != 200:
                raise Exception(f'Error code: {r and r.status_code}')
            bar()
            stream.write(r.content)
            bar()


class BasePlaylist(abc.ABC):
    _playlist: List[Union[RutubeVideo, YappyVideo]] = []

    @abc.abstractmethod
    def __init__(self, *args, **kwargs):
        ...

    def __iter__(self):
        return iter(self._playlist)

    def __next__(self):
        for video in self._playlist:
            yield video

    def __repr__(self):
        return str(self._playlist)

    def __getitem__(self, i):
        return self._playlist[i]

    @property
    def available_resolutions(self) -> List[Text]:
        return [str(v._resolution[-1]) for v in self._playlist]

    def get_best(self) -> RutubeVideo | None:
        if self._playlist:
            return self._playlist[-1]

    def get_worst(self) -> RutubeVideo | None:
        if self._playlist:
            return self._playlist[0]

    def get_by_resolution(self, value: int) -> RutubeVideo | None:
        value = int(value)
        if self._playlist:
            for video in reversed(self._playlist):
                if video._resolution[-1] == value:
                    return video


class RutubePlaylist(BasePlaylist):
    def __init__(self, data, params, *args, **kwargs):
        _playlist_dict = {}
        for playlist in data.playlists:
            res = playlist.stream_info.resolution
            if res in _playlist_dict:
                _playlist_dict[res]._reserve_path = playlist.uri
            else:
                _playlist_dict[res] = RutubeVideo(playlist, data, params)

        self._playlist: List[RutubeVideo] = list(_playlist_dict.values())


class YappyPlaylist(BasePlaylist):
    _video_id = None

    def __init__(self, video_id, *args, **kwargs):
        self._video_id = video_id
        self._playlist = [YappyVideo(self._video_id, self._get_video_link())]

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


class Rutube:
    _data_url = None
    _data = None
    _video_url = None
    _video_id = None
    _m3u8_url = None
    _m3u8_data = None
    _title = None
    _duration = None
    _playlist: RutubePlaylist | YappyPlaylist = None
    _type = VideoType.VIDEO

    def __init__(self, video_url, *args, **kwargs):
        self._video_url = video_url

        if self._check_url():
            if f'/{VideoType.SHORTS.value}/' in self._video_url:
                self._type = VideoType.SHORTS
            elif f'/{VideoType.YAPPY.value}/' in self._video_url:
                self._type = VideoType.YAPPY

            if self._type == VideoType.YAPPY:
                self._video_id = self._get_video_id()
            else:
                self._video_id = self._get_video_id()
                self._data_url = self._get_data_url()
                self._data = self._get_data()
                self._m3u8_url = self._get_m3u8_url()
                self._m3u8_data = self._get_m3u8_data()
                self._title = self._get_title()

    @property
    def is_video(self):
        return self._type == VideoType.VIDEO

    @property
    def is_shorts(self):
        return self._type == VideoType.SHORTS

    @property
    def is_yappy(self):
        return self._type == VideoType.YAPPY

    def _get_data_url(self):
        return DATA_URL_TEMPLATE.format(self._video_id)

    @property
    def _params(self):
        return dict(
            video_id=self._video_id,
            video_url=self._video_url,
            title=self._title,
            duration=self._duration,
        )

    def _get_video_id(self):
        result = re.findall(rf'{self._type.value}\/([(\w+\d+)+]+)', self._video_url)
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

    @property
    def available_resolutions(self) -> List[Text]:
        return self.playlist.available_resolutions

    def get_best(self) -> RutubeVideo | None:
        if self.playlist:
            return self._playlist.get_best()

    def get_worst(self) -> RutubeVideo | None:
        if self.playlist:
            return self.playlist.get_worst()

    def get_by_resolution(self, value: int) -> RutubeVideo | None:
        if self.playlist:
            return self.playlist.get_by_resolution(value)

    def _get_playlist(self) -> Union[RutubePlaylist, YappyPlaylist]:
        if self._type == VideoType.YAPPY:
            return YappyPlaylist(self._video_id)
        return RutubePlaylist(self._m3u8_data, self._params)

    def _get_m3u8_url(self):
        return self._data['video_balancer']['m3u8']

    def _get_m3u8_data(self):
        r = requests.get(self._m3u8_url)
        return m3u8.loads(r.text)

import pyinputplus as pyinp
rt = Rutube('https://rutube.ru/video/5c5f0ae2d9744d11a05b76bd327cbb51')
resvar = pyinp.inputInt(
    prompt=f"Select resolution between {', '.join(rt.available_resolutions)}: ",
)
print(resvar)

resvar = pyinp.inputMenu(
    [v.resolution for v in rt.playlist],
    prompt='Select resolution to download:\n',
    numbered=True,
)
rt.playlist[resvar - 1].download()
print(resvar)