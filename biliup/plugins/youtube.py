import copy
import os
import shutil
from typing import Optional

import yt_dlp

from yt_dlp import DownloadError
from yt_dlp.utils import DateRange
from biliup.config import config
from ..engine.decorators import Plugin
from . import logger
from ..engine.download import DownloadBase

VALID_URL_BASE = r'https?://(?:(?:www|m)\.)?youtube\.com/(?P<id>.*?)\??(.*?)'


@Plugin.download(regexp=VALID_URL_BASE)
class Youtube(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)

        # 从配置中获取是否开启弹幕下载
        self.ytb_danmaku = config.get('ytb_danmaku', False)

        # 从配置中获取用户的 YouTube cookie
        self.youtube_cookie = config.get('user', {}).get('youtube_cookie')

        # 从配置中获取优先的视频编码格式
        self.youtube_prefer_vcodec = config.get('youtube_prefer_vcodec')

        # 从配置中获取优先的音频编码格式
        self.youtube_prefer_acodec = config.get('youtube_prefer_acodec')

        # 从配置中获取最大的视频分辨率
        self.youtube_max_resolution = config.get('youtube_max_resolution')

        # 从配置中获取最大的视频大小
        self.youtube_max_videosize = config.get('youtube_max_videosize')

        # 从配置中获取视频的最早发布日期
        self.youtube_before_date = config.get('youtube_before_date')

        # 从配置中获取视频的最晚发布日期
        self.youtube_after_date = config.get('youtube_after_date')

        # 从配置中获取是否开启下载直播视频，默认为 True
        self.youtube_enable_download_live = config.get('youtube_enable_download_live', True)

        # 从配置中获取是否开启下载回放视频，默认为 True
        self.youtube_enable_download_playback = config.get('youtube_enable_download_playback', True)

        # 需要下载的 url
        self.download_url = None


    async def acheck_stream(self, is_check=False):
        with yt_dlp.YoutubeDL({
            'download_archive': 'archive.txt',
            'cookiefile': self.youtube_cookie,
            'ignoreerrors': True,
            'extractor_retries': 0,
        }) as ydl:
            # 获取信息的时候不设置过滤条件
            # 获取信息的时候没有过滤
            ydl_archive = copy.deepcopy(ydl.archive)
            ydl.archive = set()
            if self.download_url is not None:
                # 直播在重试时没有做特殊处理
                # 直播在重试的时候没有处理
                info = ydl.extract_info(self.download_url, download=False)
            else:
                # 获取视频信息，但不下载，并且不处理视频
                info = ydl.extract_info(self.url, download=False, process=False)
            if type(info) is not dict:
                logger.warning(f"{Youtube.__name__}: {self.url}: 获取错误")
                return False

            # 创建一个KVFileStore实例，用于缓存视频信息
            cache = KVFileStore(f"./cache/youtube/{self.fname}.txt")


            def loop_entries(entrie):
                # 判断是否为字典类型
                if type(entrie) is not dict:
                    return None
                # 如果是播放列表
                elif entrie.get('_type') == 'playlist':
                    # 遍历播放列表中的条目
                    # 播放列表递归
                    for e in entrie.get('entries'):
                        le = loop_entries(e)
                        # 如果返回的是字典类型，则返回该字典
                        if type(le) is dict:
                            return le
                        # 如果返回的是"stop"，则返回None
                        elif le == "stop":
                            return None
                # 如果是字典类型
                elif type(entrie) is dict:
                    # 判断直播状态
                    # is_upcoming 等待开播 is_live 直播中 was_live结束直播(回放)
                    # 等待开播
                    if entrie.get('live_status') == 'is_upcoming':
                        return None
                    # 直播中
                    elif entrie.get('live_status') == 'is_live':
                        # 如果未开启直播下载，则忽略
                        # 未开启直播下载忽略
                        if not self.youtube_enable_download_live:
                            return None
                    # 回放
                    elif entrie.get('live_status') == 'was_live':
                        # 如果未开启回放下载，则忽略
                        # 未开启回放下载忽略
                        if not self.youtube_enable_download_playback:
                            return None

                    # 检测是否已下载
                    if ydl._make_archive_id(entrie) in ydl_archive:
                        # 如果已下载但是还在直播则不算下载
                        if entrie.get('live_status') != 'is_live':
                            return None

                    # 查询缓存中的上传日期
                    upload_date = cache.query(entrie.get('id'))
                    # 如果缓存中无上传日期
                    if upload_date is None:
                        # 如果条目中包含上传日期
                        if entrie.get('upload_date') is not None:
                            upload_date = entrie['upload_date']
                        else:
                            # 提取上传日期
                            entrie = ydl.extract_info(entrie.get('url'), download=False, process=False)
                            # 如果提取的条目是字典类型且包含上传日期
                            if type(entrie) is dict and entrie.get('upload_date') is not None:
                                upload_date = entrie['upload_date']

                    # 如果上传日期为空，则跳过
                    # 时间是必然存在的如果不存在说明出了问题 暂时跳过
                    if upload_date is None:
                        return None
                    else:
                        # 将上传日期添加到缓存中
                        cache.add(entrie.get('id'), upload_date)

                    # 如果设置了下载日期范围，且上传日期早于下载日期范围
                    if self.youtube_after_date is not None and upload_date < self.youtube_after_date:
                        return 'stop'

                    # 检测上传日期是否在设置的日期范围内
                    # 检测时间范围
                    if upload_date not in DateRange(self.youtube_after_date, self.youtube_before_date):
                        return None

                    # 返回条目
                    return entrie
                return None

            # 调用loop_entries函数，将info作为参数传入，并将返回值赋给download_entry变量
            download_entry: Optional[dict] = loop_entries(info)
            # 判断download_entry的类型是否为字典
            if type(download_entry) is dict:
                # 判断download_entry中的live_status是否为'is_live'
                if download_entry.get('live_status') == 'is_live':
                    # 如果为'is_live'，则将self.is_download设为False
                    self.is_download = False
                else:
                    # 否则，将self.is_download设为True
                    self.is_download = True
                # 判断is_check是否为False
                if not is_check:
                    # 判断download_entry中的_type是否为'url'
                    if download_entry.get('_type') == 'url':
                        # 如果是'url'，则调用ydl.extract_info函数，将download_entry中的url作为参数传入，并将返回值重新赋给download_entry
                        download_entry = ydl.extract_info(download_entry.get('url'), download=False, process=False)
                    # 将download_entry中的title赋给self.room_title
                    self.room_title = download_entry.get('title')
                    # 将download_entry中的thumbnail赋给self.live_cover_url
                    self.live_cover_url = download_entry.get('thumbnail')
                    # 将download_entry中的webpage_url赋给self.download_url
                    self.download_url = download_entry.get('webpage_url')
                # 返回True
                return True
            else:
                # 如果download_entry不是字典类型，则返回False
                return False

    def download(self):
        filename = self.gen_download_filename(is_fmt=True)
        # 因此临时存储在其他地方
        # ydl下载的文件在下载失败时不可控
        # 临时存储在其他地方
        download_dir = f'./cache/temp/youtube/{filename}'
        try:
            ydl_opts = {
                'outtmpl': f'{download_dir}/{filename}.%(ext)s',
                'cookiefile': self.youtube_cookie,
                'break_on_reject': True,
                'download_archive': 'archive.txt',
                'format': 'bestvideo',
                # 'proxy': proxyUrl,
            }

            # 如果设置了优先的视频编码格式
            if self.youtube_prefer_vcodec is not None:
                ydl_opts['format'] += f"[vcodec~='^({self.youtube_prefer_vcodec})']"

            # 如果设置了最大视频大小并且当前是下载模式
            if self.youtube_max_videosize is not None and self.is_download:
                # 直播时无需限制文件大小
                ydl_opts['format'] += f"[filesize<{self.youtube_max_videosize}]"

            # 如果设置了最大分辨率
            if self.youtube_max_resolution is not None:
                ydl_opts['format'] += f"[height<={self.youtube_max_resolution}]"

            # 添加最佳音频格式
            ydl_opts['format'] += "+bestaudio"

            # 如果设置了优先的音频编码格式
            if self.youtube_prefer_acodec is not None:
                ydl_opts['format'] += f"[acodec~='^({self.youtube_prefer_acodec})']"

            # 如果下载目录不存在，则创建目录
            # 不能由yt_dlp创建会占用文件夹
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)

            # 使用yt_dlp进行下载
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if not self.is_download:
                    # 直播模式不过滤但是能写入过滤
                    ydl.archive = set()
                ydl.download([self.download_url])

            # 下载成功后，将文件移动到运行目录
            # 下载成功的情况下移动到运行目录
            for file in os.listdir(download_dir):
                shutil.move(f'{download_dir}/{file}', '.')

        except DownloadError as e:
            # 如果错误信息包含"Requested format is not available"
            if 'Requested format is not available' in e.msg:
                logger.error(f"{Youtube.__name__}: {self.url}: 无法获取到流，请检查vcodec,acodec,height,filesize设置")
            # 如果错误信息包含"ffmpeg is not installed"
            elif 'ffmpeg is not installed' in e.msg:
                logger.error(f"{Youtube.__name__}: {self.url}: ffmpeg未安装，无法下载")
            else:
                logger.error(f"{Youtube.__name__}: {self.url}: {e.msg}")
            return False

        finally:
            # 清理可能产生的多余文件
            try:
                # 删除ydl对象
                del ydl
                # 删除临时下载目录
                shutil.rmtree(download_dir)
            except:
                logger.error(f"{Youtube.__name__}: {self.url}: 清理残留文件失败，请手动删除{download_dir}")

        return True



class KVFileStore:
    def __init__(self, file_path):
        self.file_path = file_path
        self.cache = {}
        self._preload_data()

    def _ensure_file_and_folder_exists(self):
        folder_path = os.path.dirname(self.file_path)
        # 如果文件夹不存在，则创建文件夹
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        # 如果文件不存在，则创建空文件
        if not os.path.exists(self.file_path):
            open(self.file_path, "w").close()

    def _preload_data(self):
        self._ensure_file_and_folder_exists()
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                k, v = line.strip().split("=")
                self.cache[k] = v

    def add(self, key, value):
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
        # 更新缓存
        self.cache[key] = value

    def query(self, key, default=None):
        if key in self.cache:
            return self.cache[key]
        return default
