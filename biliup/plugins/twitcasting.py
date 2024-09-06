import hashlib

import biliup.common.util
from biliup.config import config
from biliup.Danmaku import DanmakuClient
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase
from ..plugins import logger, match1

VALID_URL_BASE = r"https?://twitcasting\.tv/([^/]+)"


@Plugin.download(regexp=VALID_URL_BASE)
class Twitcasting(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)
        # 获取配置文件中的 twitcasting_danmaku 配置项，默认为 False
        self.twitcasting_danmaku = config.get('twitcasting_danmaku', False)
        # 获取配置文件中的 twitcasting_password 配置项，默认为空字符串
        self.twitcasting_password = config.get('twitcasting_password', '')
        # 设置 fake_headers 的 referer 字段为 twitcasting 的主页链接
        self.fake_headers['referer'] = "https://twitcasting.tv/"
        if self.twitcasting_password:
            # 如果设置了 twitcasting_password，则构造 cookie 字段并添加到 fake_headers 中
            self.fake_headers[
                'cookie'] = f"wpass={hashlib.md5(self.twitcasting_password.encode(encoding='UTF-8')).hexdigest()}"
        # 初始化 movie_id 为 None
        # TODO 传递过于繁琐
        self.movie_id = None

    async def acheck_stream(self, is_check=False):
        # 使用全局变量 fake_headers 作为请求头
        # with requests.Session() as s:
        biliup.common.util.client.headers = self.fake_headers

        # 从 url 中提取 uploader_id
        uploader_id = match1(self.url, r'twitcasting.tv/([^/?]+)')
        # 发送 GET 请求获取直播信息
        response = await biliup.common.util.client.get(f'https://twitcasting.tv/streamserver.php?target={uploader_id}&mode=client&player=pc_web',
                                                       timeout=5)
        if response.status_code != 200:
            # 如果请求失败，则记录警告日志并返回 False
            logger.warning(f"{Twitcasting.__name__}: {self.url}: 获取错误，本次跳过")
            return False
        # 解析响应的 JSON 数据
        room_info = response.json()
        if not room_info:
            # 如果直播信息为空，则记录警告日志并返回 False
            logger.warning(f"{Twitcasting.__name__}: {self.url}: 直播间地址错误")
            return False
        if not room_info['movie']['live']:
            # 如果直播间未开播，则记录调试日志并返回 False
            logger.debug(f"{Twitcasting.__name__}: {self.url}: 未开播")
            return False

        # 将直播间的 movie_id 保存到实例变量中
        self.movie_id = room_info['movie']['id']

        # 发送 GET 请求获取直播间的 HTML 页面
        room_html = (await biliup.common.util.client.get(f'https://twitcasting.tv/{uploader_id}', timeout=5)).text
        if 'Enter the secret word to access' in room_html:
            # 如果直播间需要密码，则记录警告日志并返回 False
            logger.warning(f"{Twitcasting.__name__}: {self.url}: 直播间需要密码")
            return False
        # 从直播间的 HTML 页面中提取房间标题
        self.room_title = match1(room_html, r'<meta name="twitter:title" content="([^"]*)"')

        # TODO 尺寸不合适，该行代码已被注释
        # self.live_cover_url = match1(room_html, r'<meta property="og:image" content="([^"]*)"')

        # 构造直播流的 URL
        self.raw_stream_url = f"https://twitcasting.tv/{uploader_id}/metastream.m3u8?mode=source"
        return True


    def danmaku_init(self):
        # 如果开启了twitcasting弹幕功能
        if self.twitcasting_danmaku:
            # 创建一个弹幕客户端对象，传入直播间URL、生成下载文件名以及包含movie_id和password的字典
            self.danmaku = DanmakuClient(self.url, self.gen_download_filename(), {
                'movie_id': self.movie_id,
                'password': self.twitcasting_password,
            })


#
# class TwitcastingUtils:
#     import hashlib
#
#     def _getBroadcaster(html_text: str) -> dict:
#         _info = {}
#         _info['ID'] = match1(html_text, VALID_URL_BASE)
#         _info['Title'] = match1(
#             html_text,
#             r'<meta name="twitter:title" content="([^"]*)"'
#         )
#         _info['MovieID'] = match1(
#             match1(
#                 html_text,
#                 r'<meta name="twitter:image" content="([^"]*)"'
#             ),
#             r'/(\d+)'
#         )
#         _info['web-authorize-session-id'] = json.loads(
#             match1(
#                 html_text,
#                 r'<meta name="tc-page-variables" content="([^"]+)"'
#             ).replace(
#                 '&quot;',
#                 '"'
#             )
#         ).get('web-authorize-session-id')
#         return _info
#
#     def _generate_authorizekey(salt: str, timestamp: str, method: str, pathname: str, search: str,
#                                sessionid: str) -> str:
#         _hash_str = salt + timestamp + method + pathname + search + sessionid
#         return str(timestamp + "." + TwitcastingUtils.hashlib.sha256(_hash_str.encode()).hexdigest())
# '''
# X-Web-Authorizekey 可在 PlayerPage2.js 文件中
# 通过 return ""[u(413)](m, ".")[u(413)](f) 所在的方法计算而出
# 由 salt + 10位 timestamp + 接口Method大写 + 接口pathname + 接口search + web-authorize-session-id 拼接后
# 再经过 SHA-256 处理，最后在字符串前面拼接上 10位 timestamp 和 dot 得到
# '''
# __n = int(time.time() * 1000)
# _salt = "d6g97jormun44naq"
# _time = str(__n)[:10]
# _method = "GET"
# _pathname = f"/users/{boardcasterInfo['ID']}/latest-movie"
# _search = "?__n=" + str(__n)
#
# s.headers.update({
#     "X-Web-Authorizekey": TwitcastingUtils._generate_authorizekey(
#         _salt,
#         _time,
#         _method,
#         _pathname,
#         _search,
#         boardcasterInfo['web-authorize-session-id']
#     ),
#     "X-Web-Sessionid": boardcasterInfo['web-authorize-session-id'],
# })
# params = {"__n": __n}
# r = s.get(f"https://frontendapi.twitcasting.tv{_pathname}", params=params, timeout=5).json()
# if not r['movie']['is_on_live']:
#     return False
#
# if boardcasterInfo['ID']:
#     params = {
#         "mode": "client",
#         "target": boardcasterInfo['ID']
#     }
#     _stream_info = s.get("https://twitcasting.tv/streamserver.php", params=params, timeout=5).json()
#     if not _stream_info['movie']['live']:
#         return False
#     if is_check:
#         return True
