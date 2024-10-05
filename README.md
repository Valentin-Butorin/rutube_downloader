# Rutube Downloader

## Get it

```python
pip install rutube-downloader
```

## Try it

```python
from rutube import Rutube

rt = Rutube('https://rutube.ru/video/5c5f0ae2d9744d11a05b76bd327cbb51/')

# Get a list of videos
# Each object is the same video but with different resolution
print(rt.playlist)  # [Nature 4k (272x480), Nature 4k (408x720), Nature 4k (608x1080)]

# Get a list of available resolutions
print(rt.available_resolutions)  # ['480', '720', '1080']

# Download a video with specific resolution and save it to the current directory 
rt.get_by_resolution(720).download()

# Download a video with the best quality and save it to specific directory 
# Path may be absolute or relative
rt.get_best().download('downloads/saved-videos')
```

## Features

### Get video with specific resolution

```python
from rutube import Rutube

rt = Rutube('https://rutube.ru/video/5c5f0ae2d9744d11a05b76bd327cbb51/')

# Returns a video with the best quality
rt.get_best()

# Returns a video with the worst quality
rt.get_worst()

# Returns None if not found
rt.get_by_resolution(1080)

# Returns a list of integers - [480, 720, 1080]
rt.available_resolutions
```

### Writing to bytes

```python
from rutube import Rutube
from io import BytesIO, FileIO

rt = Rutube('https://rutube.ru/video/5c5f0ae2d9744d11a05b76bd327cbb51/')

with open('video.mp4', 'wb') as f:
    rt.get_best().download(stream=f)

with BytesIO() as stream:
    rt.get_best().download(stream=stream)

with FileIO() as file:
    rt.get_best().download(stream=file)
```

### Faster downloading
Downloading using threads. Call _download()_ with number of workers as argument.

> [!WARNING]
> It's expensive way to download. Be careful to use it!

```python
from rutube import Rutube

rt = Rutube('https://rutube.ru/video/5c5f0ae2d9744d11a05b76bd327cbb51/')

rt.get_best().download(workers=8)
```
