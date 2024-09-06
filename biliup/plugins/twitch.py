import io
import random
import re
import socket
import subprocess
import time
from typing import AsyncGenerator, List
from urllib.parse import urlencode

import yt_dlp

from biliup.common.util import client
from biliup.config import config
from biliup.Danmaku import DanmakuClient
from . import logger
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase, BatchCheck

VALID_URL_BASE = r'(?:https?://)?(?:(?:www|go|m)\.)?twitch\.tv/(?P<id>[0-9_a-zA-Z]+)'
VALID_URL_VIDEOS = r'https?://(?:(?:www|go|m)\.)?twitch\.tv/(?P<id>[^/]+)/(?:videos|profile|clips)'
_CLIENT_ID = 'kimne78kx3ncx6brgo4mv6wki5h1ko'


@Plugin.download(regexp=VALID_URL_VIDEOS)
class TwitchVideos(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        # 调用父类的初始化方法
        DownloadBase.__init__(self, fname, url, suffix=suffix)
        # 设置下载标志为True
        self.is_download = True
        # 初始化twitch_download_entry为None
        self.twitch_download_entry = None

    async def acheck_stream(self, is_check=False):
        while True:
            # 获取twitch的认证token
            auth_token = TwitchUtils.get_auth_token()
            if auth_token:
                # 构造cookie字符串
                cookie = io.StringIO(f"""# Netscape HTTP Cookie File
.twitch.tv	TRUE	/	FALSE	0	auth-token	{auth_token}
""")
            else:
                # 如果没有认证token，则cookie为None
                cookie = None

            # 初始化YoutubeDL对象，并设置相关参数
            with yt_dlp.YoutubeDL({'download_archive': 'archive.txt', 'cookiefile': cookie}) as ydl:
                try:
                    # 提取url的信息，但不进行下载和进程处理
                    info = ydl.extract_info(self.url, download=False, process=False)
                    for entry in info['entries']:
                        # 如果该条目已经在下载存档中，则跳过
                        if ydl.in_download_archive(entry):
                            continue
                        if not is_check:
                            # 提取条目的信息，但不进行下载
                            download_info = ydl.extract_info(entry['url'], download=False)
                            # 设置房间标题
                            self.room_title = download_info['title']
                            # 设置原始直播流地址
                            self.raw_stream_url = download_info['url']
                            # 获取缩略图列表
                            thumbnails = download_info.get('thumbnails')
                            if type(thumbnails) is list and len(thumbnails) > 0:
                                # 设置直播封面地址
                                self.live_cover_url = thumbnails[len(thumbnails) - 1].get('url')
                            # 设置twitch的下载条目
                            self.twitch_download_entry = entry
                        # 返回True表示检查成功
                        return True
                except Exception as e:
                    # 如果异常信息中包含'Unauthorized'，则无效认证token并继续循环
                    if 'Unauthorized' in str(e):
                        TwitchUtils.invalid_auth_token()
                        continue
                    else:
                        # 记录警告日志并包含异常信息
                        logger.warning(f"{self.url}：获取错误", exc_info=True)
                # 返回False表示检查失败
                return False

    def download_success_callback(self):
        # 初始化YoutubeDL对象，并设置相关参数
        with yt_dlp.YoutubeDL({'download_archive': 'archive.txt'}) as ydl:
            # 将twitch的下载条目添加到下载存档中
            ydl.record_download_archive(self.twitch_download_entry)



@Plugin.download(regexp=VALID_URL_BASE)
class Twitch(DownloadBase, BatchCheck):
    def __init__(self, fname, url, suffix='flv'):
        # 调用父类构造函数进行初始化
        DownloadBase.__init__(self, fname, url, suffix=suffix)

        # 从配置中获取 twitch_danmaku 的值，默认为 False
        self.twitch_danmaku = config.get('twitch_danmaku', False)

        # 从配置中获取 twitch_disable_ads 的值，默认为 True
        self.twitch_disable_ads = config.get('twitch_disable_ads', True)

        # 初始化进程对象为 None
        self.__proc = None

    async def acheck_stream(self, is_check=False):
        # 从 URL 中提取频道名称
        channel_name = re.match(VALID_URL_BASE, self.url).group('id').lower()

        # 调用 TwitchUtils 的 post_gql 方法发送 GraphQL 查询
        user = (await TwitchUtils.post_gql({
            "query": '''
                query query($channel_name:String!) {
                    user(login: $channel_name){
                        stream {
                            id
                            title
                            type
                            previewImageURL(width: 0,height: 0)
                            playbackAccessTokenken(
                                params: {
                                    platform: "web",
                                    playerBackend: "mediaplayer",
                                    playerType: "site"
                                }
                            ) {
                                signature
                                value
                            }
                        }
                    }
                }
            ''',
            'variables': {'channel_name': channel_name}
        })).get('data', {}).get('user')

        # 如果获取的用户信息为空
        if not user:
            # 记录警告日志并输出异常信息
            logger.warning(f"{Twitch.__name__}: {self.url}: 获取错误", exc_info=True)
            return False

        # 如果用户没有直播或者直播类型不是 live
        elif not user['stream'] or user['stream']['type'] != 'live':
            return False

        # 设置直播间的标题
        self.room_title = user['stream']['title']

        # 设置直播封面图片的 URL
        self.live_cover_url = user['stream']['previewImageURL']

        # 如果只是进行检查，则返回 True
        if is_check:
            return True


        # https://github.com/biliup/biliup/issues/991
        if self.downloader == 'ffmpeg':
            # 创建套接字
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # 绑定到本地主机的随机端口
                s.bind(('localhost', 0))
                # 获取绑定的端口号
                port = s.getsockname()[1]

            # 定义启动流媒体的命令行列表
            stream_shell = [
                "streamlink",
                "--player-external-http",  # 为外部程序提供流媒体数据
                "--player-external-http-port", str(port),  # 对外部输出流的端口
                "--player-external-http-interface", "localhost",

                # 下面是可选参数
                # "--twitch-disable-ads",                     # 去广告，去掉、跳过嵌入的广告流
                # "--twitch-disable-hosting",               # 该参数从5.0起已被禁用
                "--twitch-disable-reruns",  # 如果该频道正在重放回放，不打开流
                self.url, "best"  # 流链接
            ]

            # 如果需要禁用广告，则在命令行列表中插入相应的参数
            if self.twitch_disable_ads:  # 去广告，去掉、跳过嵌入的广告流
                stream_shell.insert(1, "--twitch-disable-ads")

            # 获取Twitch的认证令牌
            auth_token = TwitchUtils.get_auth_token()

            # 如果存在且有效，则在命令行列表中插入认证令牌的参数
            # 在设置且有效的情况下使用
            if auth_token:
                stream_shell.insert(1, f"--twitch-api-header=Authorization=OAuth {auth_token}")

            # 启动子进程执行命令行
            self.__proc = subprocess.Popen(stream_shell)

            # 设置原始流媒体的URL
            self.raw_stream_url = f"http://localhost:{port}"

            # 等待子进程启动成功或超时
            i = 0
            while i < 5:
                if not (self.__proc.poll() is None):
                    return False
                time.sleep(1)
                i += 1

            return True
        else:
            # 定义查询参数
            query = {
                "player": "twitchweb",
                "p": random.randint(1000000, 10000000),
                "allow_source": "true",
                "allow_audio_only": "true",
                "allow_spectre": "false",
                'fast_bread': "true",
                'sig': user.get('stream').get('playbackAccessToken').get('signature'),
                'token': user.get('stream').get('playbackAccessToken').get('value'),
            }

            # 构造原始流媒体的URL
            self.raw_stream_url = f'https://usher.ttvnw.net/api/channel/hls/{channel_name}.m3u8?{urlencode(query)}'

            return True


    @staticmethod
    async def abatch_check(check_urls: List[str]) -> AsyncGenerator[str, None]:
        # 初始化操作列表
        ops = []
        # 遍历待检查的URL列表
        for url in check_urls:
            # 使用正则表达式从URL中提取频道名
            channel_name = re.match(VALID_URL_BASE, url).group('id')
            # 构建GraphQL操作对象
            op = {
                "query": '''
                    query query($login:String!) {
                        user(login: $login){
                            stream {
                              type
                            }
                        }
                    }
                ''',
                'variables': {'login': channel_name.lower()}
            }
            # 将操作添加到操作列表中
            ops.append(op)

        # 批量执行GraphQL查询操作
        gql = await TwitchUtils.post_gql(ops)

        # 遍历查询结果
        for index, data in enumerate(gql):
            # 获取用户数据
            user = data.get('data', {}).get('user')
            # 如果用户数据不存在，记录警告并跳过当前循环
            if not user:
                logger.warning(f"{Twitch.__name__}: {check_urls[index]}: 获取错误")
                continue
            # 如果用户没有直播或直播类型不是live，跳过当前循环
            elif not user['stream'] or user['stream']['type'] != 'live':
                continue
            # 产出当前URL
            yield check_urls[index]


    def danmaku_init(self):
        # 如果开启twitch弹幕功能
        if self.twitch_danmaku:
            # 创建一个弹幕客户端对象，传入直播间URL和生成的下载文件名
            self.danmaku = DanmakuClient(self.url, self.gen_download_filename())

    def close(self):
        try:
            # 如果子进程不为空
            if self.__proc is not None:
                # 终止子进程
                self.__proc.terminate()
                # 等待子进程结束，超时时间为5秒
                self.__proc.wait(timeout=5)
        # 如果等待超时
        except subprocess.TimeoutExpired:
            # 强制杀死子进程
            self.__proc.kill()
        # 如果发生其他异常
        except:
            # 记录异常日志，并输出关闭文件名失败的提示信息
            logger.exception(f'terminate {self.fname} failed')
        finally:
            # 无论是否发生异常，都将子进程对象置为空
            self.__proc = None



class TwitchUtils:
    # Twitch已失效的auth_token
    _invalid_auth_token = None

    @staticmethod
    def get_auth_token():
        # 从配置中获取twitch的认证token
        auth_token = config.get('user', {}).get('twitch_cookie')
        # 如果当前的无效认证token和获取到的认证token相同
        if TwitchUtils._invalid_auth_token == auth_token:
            # 返回None
            return None
        return auth_token

    @staticmethod
    def invalid_auth_token():
        # 将配置中的twitch的认证token设置为无效认证token
        TwitchUtils._invalid_auth_token = config.get('user', {}).get('twitch_cookie')
        # 记录警告日志，提示用户twitch的cookie已失效，请及时更换
        logger.warning("Twitch Cookie已失效请及时更换，后续操作将忽略Twitch Cookie")

    @staticmethod
    async def post_gql(ops):
        headers = {
            'Content-Type': 'text/plain;charset=UTF-8',
            'Client-ID': _CLIENT_ID,
        }
        # 获取twitch的认证token
        auth_token = TwitchUtils.get_auth_token()
        if auth_token:
            # 如果获取到认证token，则在请求头中添加Authorization字段
            headers['Authorization'] = f'OAuth {auth_token}'

        if isinstance(ops, list):
            # 批量操作的数量限制为30
            limit = 30
            # 将ops列表按照每30个一组进行切分
            ops_list = [ops[i:i + limit] for i in range(0, len(ops), limit)]
            data = []
            for __ops in ops_list:
                # 调用私有方法发送GraphQL请求，并等待结果
                __data = await TwitchUtils.__post_gql(headers, __ops)
                if __data: # 让检测不抛出异常
                    # 如果结果不为空，则将其追加到data列表中
                    data.extend(__data)
            return data

        # 如果ops不是列表类型，则直接调用私有方法发送GraphQL请求，并返回结果
        # 正常下载由上层方法处理
        return await TwitchUtils.__post_gql(headers, ops)


    @staticmethod
    async def __post_gql(headers, ops):
        try:
            # 发送POST请求到Twitch的 GraphQL API
            _resp = await client.post(
                'https://gql.twitch.tv/gql',
                json=ops,
                headers=headers,
                timeout=15)

            # 检查请求响应状态，如果有错误则抛出异常
            _resp.raise_for_status()

            # 将响应内容解析为JSON格式
            gql = _resp.json()

            # 如果返回的结果是字典且包含'error'键，并且'error'的值为'Unauthorized'
            if isinstance(gql, dict) and gql.get('error') == 'Unauthorized':
                # 调用invalid_auth_token方法，标记当前的认证token为无效
                TwitchUtils.invalid_auth_token()

                # 递归调用post_gql方法，重新发送请求
                return await TwitchUtils.post_gql(ops)

            # 返回解析后的JSON结果
            return gql

        except:
            # 捕获异常并记录日志，同时输出当前请求的ops内容
            logger.exception(f"Twitch - post_gql: {ops}")

        # 如果出现异常，则返回空字典
        return {}
