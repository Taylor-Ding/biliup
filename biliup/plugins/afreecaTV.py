import time
from typing import Optional, Dict

import requests

import biliup.common.util
from biliup.config import config
from ..common import tools
from ..common.tools import NamedLock
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase
from ..plugins import match1, logger

# VALID_URL_BASE = r"https?://(.*?)\.afreecatv\.com/(?P<username>\w+)(?:/\d+)?"
VALID_URL_BASE = r"https?://play\.afreecatv\.com/(?P<username>\w+)(?:/\d+)?"
CHANNEL_API_URL = "https://live.afreecatv.com/afreeca/player_live_api.php"

QUALITIES = ["original", "hd4k", "hd", "sd"]


@Plugin.download(regexp=r"https?://(.*?)\.afreecatv\.com/(?P<username>\w+)(?:/\d+)?")
class AfreecaTV(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)
        # 如果获取到了cookie，则将其添加到fake_headers中
        if AfreecaTVUtils.get_cookie():
            self.fake_headers['cookie'] = ';'.join(
                [f"{name}={value}" for name, value in AfreecaTVUtils.get_cookie().items()])

    async def acheck_stream(self, is_check=False):
        try:
            # 从url中提取用户名
            username = match1(self.url, VALID_URL_BASE)
            if not username:
                # 如果用户名不存在，则输出警告并返回False
                logger.warning(f"{AfreecaTV.__name__}: {self.url}: 直播间地址错误")
                return False

            # 发送POST请求获取频道信息
            channel_info = (await biliup.common.util.client.post(CHANNEL_API_URL, data={
                "bid": username,
                "bno": "",
                "type": "live",
                "pwd": "",
                "player_type": "html5",
                "stream_type": "common",
                "quality": QUALITIES[0],
                "mode": "landing",
                "from_api": 0,
            }, headers=self.fake_headers, timeout=5)).json()

            # 如果频道信息中RESULT为-6，则输出警告并返回False
            if channel_info["CHANNEL"]["RESULT"] == -6:
                logger.warning(f"{AfreecaTV.__name__}: {self.url}: 检测失败,请检查账号密码设置")
                return False

            # 如果频道信息中RESULT不为1，则返回False
            if channel_info["CHANNEL"]["RESULT"] != 1:
                return False

            # 获取直播间的标题
            self.room_title = channel_info["CHANNEL"]["TITLE"]

            # 如果is_check为True，则返回True
            if is_check:
                return True

            # 发送POST请求获取aid信息
            aid_info = (await biliup.common.util.client.post(CHANNEL_API_URL, data={
                "bid": username,
                "bno": channel_info["CHANNEL"]["BNO"],
                "type": "aid",
                "pwd": "",
                "player_type": "html5",
                "stream_type": "common",
                "quality": QUALITIES[0],
                "mode": "landing",
                "from_api": 0,
            }, headers=self.fake_headers, timeout=5)).json()

            # 发送GET请求获取观看信息
            view_info = (await biliup.common.util.client.get(f'{channel_info["CHANNEL"]["RMD"]}/broad_stream_assign.html', params={
                "return_type": channel_info["CHANNEL"]["CDN"],
                "broad_key": f'{channel_info["CHANNEL"]["BNO"]}-common-{QUALITIES[0]}-hls'
            }, headers=self.fake_headers, timeout=5)).json()

            # 拼接原始直播流地址
            self.raw_stream_url = view_info["view_url"] + "?aid=" + aid_info["CHANNEL"]["AID"]
        except:
            # 如果出现异常，则输出警告并返回False
            logger.warning(f"{AfreecaTV.__name__}: {self.url}: 获取错误，本次跳过")
            return False

        return True



class AfreecaTVUtils:
    _cookie: Optional[Dict[str, str]] = None
    _cookie_expires = None

    @staticmethod
    def get_cookie() -> Optional[Dict[str, str]]:
        with NamedLock("AfreecaTV_cookie_get"):
            # 如果cookie为空或者cookie已过期
            if not AfreecaTVUtils._cookie or AfreecaTVUtils._cookie_expires <= time.time():
                # 从配置中获取AfreecaTV的用户名和密码
                username = config.get('user', {}).get('afreecatv_username', '')
                password = config.get('user', {}).get('afreecatv_password', '')
                # 如果用户名或密码为空，则返回None
                if not username or not password:
                    return None
                # 发送登录请求
                response = requests.post("https://login.afreecatv.com/app/LoginAction.php", data={
                    "szUid": username,
                    "szPassword": password,
                    "szWork": "login",
                    "szType": "json",
                    "isSaveId": "true",
                    "isSavePw": "true",
                    "isSaveJoin": "true",
                    "isLoginRetain": "Y",
                })
                # 如果登录失败，则返回None
                if response.json()["RESULT"] != 1:
                    return None

                # 从响应中获取cookie字典
                cookie_dict = response.cookies.get_dict()
                # 提取需要的cookie字段并保存到_cookie中
                AfreecaTVUtils._cookie = {
                    "RDB": cookie_dict["RDB"],
                    "PdboxBbs": cookie_dict["PdboxBbs"],
                    "PdboxTicket": cookie_dict["PdboxTicket"],
                    "PdboxSaveTicket": cookie_dict["PdboxSaveTicket"],
                }
                # 设置cookie过期时间为7天后
                AfreecaTVUtils._cookie_expires = time.time() + (7 * 24 * 60 * 60)

            # 返回_cookie
            return AfreecaTVUtils._cookie

