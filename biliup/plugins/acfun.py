import random
import string
import json
import requests

import biliup.common.util
from . import logger
from ..common import tools
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase


@Plugin.download(regexp=r'(?:https?://)?(?:(?:www|m|live)\.)?acfun\.cn')
class Acfun(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)

    async def acheck_stream(self, is_check=False):
        # 检查URL是否包含acfun.cn/live/
        if len(self.url.split("acfun.cn/live/")) < 2:
            logger.debug("直播间地址错误")
            return False

        # 获取直播间ID
        rid = self.url.split("acfun.cn/live/")[1]

        # 生成随机did
        did = "web_"+get_random_name(16)

        # 设置cookies
        cookies = dict(_did=did)

        # 发送登录请求，获取用户信息
        data1 = {'sid': 'acfun.api.visitor'}
        r1 = await biliup.common.util.client.post("https://id.app.acfun.cn/rest/app/visitor/login",
                                                  headers=self.fake_headers, data=data1, cookies=cookies)

        # 提取用户ID和访问状态
        userid = r1.json()['userId']
        visitorst = r1.json()['acfun.api.visitor_st']

        # 设置请求参数
        params = {
            "subBiz": "mainApp",
            "kpn": "ACFUN_APP",
            "kpf": "PC_WEB",
            "userId": str(userid),
            "did": did,
            "acfun.api.visitor_st": visitorst
        }

        # 发送获取直播流地址的请求
        data2 = {'authorId': rid, 'pullStreamType': 'FLV'}
        self.fake_headers['referer'] = "https://live.acfun.cn/"
        r2 = await biliup.common.util.client.post("https://api.kuaishouzt.com/rest/zt/live/web/startPlay",
                                                  headers=self.fake_headers, data=data2, params=params)

        # 检查请求结果
        if r2.json().get('result') != 1:
            logger.debug(r2.json())
            return False

        # 解析直播流地址和房间标题
        d = r2.json()['data']['videoPlayRes']
        self.raw_stream_url = json.loads(d)['liveAdaptiveManifest'][0]['adaptationSet']['representation'][-1]['url']
        self.room_title = r2.json()['data']['caption']

        return True

# 生成随机名称的函数
def get_random_name(numb):
    return random.choice(string.ascii_lowercase) + \
        ''.join(random.sample(string.ascii_letters + string.digits, numb - 1))
