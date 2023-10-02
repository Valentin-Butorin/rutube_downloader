# Rutube Downloader

## Get it
```python
pip install rutube-downloader
```

## Try it
```python
from rutube import Rutube

rt = Rutube('https://rutube.ru/video/5c5f0ae2d9744d11a05b76bd327cbb51/')

print(rt.playlist)  # [Nature 4k (272x480), Nature 4k (408x720), Nature 4k (608x1080)]

rt.playlist[-1].download()
```
