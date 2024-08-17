# Rutube Downloader

## Get it
```python
pip install rutube-downloader
```

## Try it
```python
from rutube import Rutube
from io import BytesIO

rt = Rutube('https://rutube.ru/video/5c5f0ae2d9744d11a05b76bd327cbb51/')

print(rt.playlist)  # [Nature 4k (272x480), Nature 4k (408x720), Nature 4k (608x1080)]

video = rt.playlist[-1]
video.download()  # Download a file and save it to the current directory 
video.download('downloads\saved-videos')  # Path may be absolute or relative

with open('video.mp4', 'wb') as f:
    video.download(stream=f)

with BytesIO() as stream:  # Or FileIO with wb/rb+ mode
    video.download(stream=stream)


```
