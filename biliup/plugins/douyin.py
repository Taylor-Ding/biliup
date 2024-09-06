import json
from typing import Optional
from urllib.parse import unquote, urlparse, parse_qs, urlencode, urlunparse

import requests

from biliup.common.util import client
from . import logger, match1, random_user_agent
from biliup.config import config
from biliup.Danmaku import DanmakuClient
from ..common.tools import NamedLock
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase


@Plugin.download(regexp=r'(?:https?://)?(?:(?:www|m|live|v)\.)?douyin\.com')
class Douyin(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        # 调用父类的初始化方法
        super().__init__(fname, url, suffix)
        # 获取配置文件中的douyin_danmaku配置项，默认为False
        self.douyin_danmaku = config.get('douyin_danmaku', False)
        # 设置fake_headers中的user-agent字段为DouyinUtils中定义的DOUYIN_USER_AGENT
        self.fake_headers['user-agent'] = DouyinUtils.DOUYIN_USER_AGENT
        # 设置fake_headers中的referer字段为抖音直播的链接
        self.fake_headers['referer'] = "https://live.douyin.com/"
        # 从配置文件中获取user配置项下的douyin_cookie字段，默认为空字符串
        self.fake_headers['cookie'] = config.get('user', {}).get('douyin_cookie', '')
        # 初始化网页端房间号或抖音号，默认为None
        self.__web_rid = None # 网页端房间号 或 抖音号
        # 初始化单场直播的直播房间，默认为None
        self.__room_id = None # 单场直播的直播房间
        # 初始化sec_uid，默认为None
        self.__sec_uid = None


    async def acheck_stream(self, is_check=False):

        # 如果fake_headers中的cookie不包含ttwid，则添加ttwid
        if "ttwid" not in self.fake_headers['cookie']:
            self.fake_headers['Cookie'] = f'ttwid={DouyinUtils.get_ttwid()};{self.fake_headers["cookie"]}'

        # 如果url中包含"v.douyin"，则执行以下逻辑
        if "v.douyin" in self.url:
            try:
                # 发送GET请求，获取响应
                resp = await client.get(self.url, headers=self.fake_headers, follow_redirects=False)
            except:
                return False
            try:
                # 如果响应状态码不是301或302，则抛出异常
                if resp.status_code not in {301, 302}:
                    raise
                # 获取重定向的URL
                next_url = str(resp.next_request.url)
                # 如果重定向的URL中不包含"webcast.amemv"，则抛出异常
                if "webcast.amemv" not in next_url:
                    raise
            except:
                logger.error(f"{self.plugin_msg}: 不支持的链接")
                return False
            # 从重定向的URL中提取sec_user_id和room_id
            self.__sec_uid = match1(next_url, r"sec_user_id=(.*?)&")
            self.__room_id = match1(next_url.split("?")[0], r"(\d+)")
        # 如果url中包含"/user/"，则执行以下逻辑
        elif "/user/" in self.url:
            # 提取sec_uid
            sec_uid = self.url.split("user/")[1].split("?")[0]
            # 如果sec_uid长度为55，则赋值给self.__sec_uid
            if len(sec_uid) == 55:
                self.__sec_uid = sec_uid
            else:
                try:
                    # 发送GET请求，获取用户页面的文本内容
                    user_page = (await client.get(self.url, headers=self.fake_headers)).text
                    # 从用户页面的文本内容中提取web_rid
                    user_page_data = unquote(
                        user_page.split('<script id="RENDER_DATA" type="application/json">')[1].split('</script>')[0])
                    web_rid = match1(user_page_data, r'"web_rid":"([^"]+)"')
                    # 如果web_rid为空，则打印日志并返回False
                    if not web_rid:
                        logger.debug(f"{self.plugin_msg}: 未开播")
                        return False
                    # 赋值给self.__web_rid
                    self.__web_rid = web_rid
                except (KeyError, IndexError):
                    logger.error(f"{self.plugin_msg}: 房间号获取失败，请检查Cookie设置")
                    return False
                except:
                    logger.exception(f"{self.plugin_msg}: 房间号获取失败")
                    return False
        # 如果以上两种情况都不满足，则执行以下逻辑
        else:
            # 从url中提取web_rid
            web_rid = self.url.split('douyin.com/')[1].split('/')[0].split('?')[0]
            # 如果web_rid以"+"开头，则去掉"+"
            if web_rid[0] == "+":
                web_rid = web_rid[1:]
            # 赋值给self.__web_rid
            self.__web_rid = web_rid


        try:
            _room_info = None
            if self.__web_rid:
                # 如果存在 web_rid，则获取网页端房间信息
                _room_info = await self.get_web_room_info(self.__web_rid)
                if _room_info:
                    if not _room_info['data'].get('user'):
                        # 如果没有用户信息，可能是用户被封禁
                        # 可能是用户被封禁
                        raise Exception(f"{str(_room_info)}")
                    # 获取 sec_uid
                    self.__sec_uid = _room_info['data']['user']['sec_uid']

            # 如果 _room_info 中没有数据，则尝试获取其他来源的房间信息
            # PCWeb 端无流 或 没有提供 web_rid
            if not _room_info.get('data', {}).get('data'):
                _room_info = await self.get_room_info(self.__sec_uid, self.__room_id)
                if _room_info['data'].get('room', {}).get('owner'):
                    # 更新 web_rid
                    self.__web_rid = _room_info['data']['room']['owner']['web_rid']

            try:
                # 尝试获取直播流信息
                # 如果出现异常，则不提示，直接到 移动网页 端获取
                # 出现异常不用提示，直接到 移动网页 端获取
                room_info = _room_info['data']['data'][0]
            except (KeyError, IndexError):
                # 如果 移动网页 端也没有数据，则当做未开播处理
                # 如果 移动网页 端也没有数据，当做未开播处理
                room_info = _room_info['data'].get('room', {})

            # 如果 room_info 中没有数据，则当做未开播处理
            # 当做未开播处理
            # if not room_info:
            #     logger.info(f"{self.plugin_msg}: 获取直播间信息失败 {_room_info}")

            # 检查直播状态，如果未开播，则记录日志并返回 False
            if room_info.get('status') != 2:
                logger.debug(f"{self.plugin_msg}: 未开播")
                return False

            # 更新 room_id
            self.__room_id = room_info['id_str']

        except:
            # 如果获取直播间信息失败，则记录异常并返回 False
            logger.exception(f"{self.plugin_msg}: 获取直播间信息失败")
            return False

        # 如果 is_check 为 True，则返回 True
        if is_check:
            return True

        try:
            # 加载直播流数据
            pull_data = room_info['stream_url']['live_core_sdk_data']['pull_data']
            if room_info['stream_url'].get('pull_datas') and config.get('douyin_extra_record', True):
                # 如果存在 pull_datas，并且配置允许额外记录，则使用 pull_datas 中的数据
                pull_data = next(iter(room_info['stream_url']['pull_datas'].values()))

            # 解析 stream_data
            stream_data = json.loads(pull_data['stream_data'])['data']

        except:
            # 如果加载直播流失败，则记录异常并返回 False
            logger.exception(f"{self.plugin_msg}: 加载直播流失败")
            return False


        # 原画origin 蓝光uhd 超清hd 高清sd 标清ld 流畅md 仅音频ao
        quality_items = ['origin', 'uhd', 'hd', 'sd', 'ld', 'md']
        quality = config.get('douyin_quality', 'origin')
        if quality not in quality_items:
            quality = quality_items[0]
        try:
            # 如果没有这个画质则取相近的 优先低清晰度
            if quality not in stream_data:
                # 可选的清晰度 含自身
                optional_quality_items = [x for x in quality_items if x in stream_data.keys() or x == quality]
                # 自身在可选清晰度的位置
                optional_quality_index = optional_quality_items.index(quality)
                # 自身在所有清晰度的位置
                quality_index = quality_items.index(quality)
                # 高清晰度偏移
                quality_left_offset = None
                # 低清晰度偏移
                quality_right_offset = None

                # 如果可选清晰度列表中当前画质右侧还有画质
                if optional_quality_index + 1 < len(optional_quality_items):
                    # 计算右侧偏移量
                    quality_right_offset = quality_items.index(
                        optional_quality_items[optional_quality_index + 1]) - quality_index

                # 如果可选清晰度列表中当前画质左侧还有画质
                if optional_quality_index - 1 >= 0:
                    # 计算左侧偏移量
                    quality_left_offset = quality_index - quality_items.index(
                        optional_quality_items[optional_quality_index - 1])

                # 如果右侧偏移量小于等于左侧偏移量
                # 取相邻的清晰度
                if quality_right_offset <= quality_left_offset:
                    quality = optional_quality_items[optional_quality_index + 1]
                else:
                    quality = optional_quality_items[optional_quality_index - 1]

            # 根据配置获取协议类型，默认为'flv'
            protocol = 'hls' if config.get('douyin_protocol') == 'hls' else 'flv'
            # 根据画质和协议获取原始流地址
            self.raw_stream_url = stream_data[quality]['main'][protocol]
            # 获取房间标题
            self.room_title = room_info['title']
        except:
            logger.exception(f"{self.plugin_msg}: 寻找清晰度失败")
            return False
        return True


    def danmaku_init(self):
        if self.douyin_danmaku:
            # 弹幕初始化内容
            content = {
                'web_rid': self.__web_rid,
                'sec_uid': self.__sec_uid,
                'room_id': self.__room_id,
            }
            try:
                import jsengine
                try:
                    # 尝试初始化 JavaScript 引擎
                    jsengine.jsengine()
                    # 创建弹幕客户端
                    self.danmaku = DanmakuClient(self.url, self.gen_download_filename(), content)
                except jsengine.exceptions.RuntimeError as e:
                    extra_msg = "如需录制抖音弹幕，"
                    # 抛出异常，提示需要安装至少一个 Javascript 解释器
                    logger.error(f"\n{e}\n{extra_msg}请至少安装一个 Javascript 解释器，如 pip install quickjs")
            except:
                pass

    async def get_web_room_info(self, web_rid) -> dict:
        # 构建请求 URL
        target_url = DouyinUtils.build_request_url(f"https://live.douyin.com/webcast/room/web/enter/?web_rid={web_rid}")
        # 发送 GET 请求，获取网页房间信息
        web_info = (await client.get(target_url, headers=self.fake_headers)).json()
        return web_info

    async def get_room_info(self, sec_user_id, room_id) -> dict:
        if not sec_user_id:
            raise ValueError("sec_user_id is None")
        # 构建请求参数
        params = {
            'type_id': 0,
            'live_id': 1,
            'version_code': '99.99.99',
            'app_id': 1128,
            'room_id': room_id if room_id else 2, # 必要但不校验
            'sec_user_id': sec_user_id
        }
        # 发送 GET 请求，获取房间信息
        info = (await client.get("https://webcast.amemv.com/webcast/room/reflow/info/",
                    params=params, headers=self.fake_headers)).json()
        return info

class DouyinUtils:
    # 抖音ttwid
    _douyin_ttwid: Optional[str] = None

    # 随机生成用户代理
    # DOUYIN_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36'
    DOUYIN_USER_AGENT = random_user_agent()
    DOUYIN_HTTP_HEADERS = {
        'User-Agent': DOUYIN_USER_AGENT
    }

    @staticmethod
    def get_ttwid() -> Optional[str]:
        # 使用命名锁确保并发安全
        with NamedLock("douyin_ttwid_get"):
            # 如果_douyin_ttwid为空
            if not DouyinUtils._douyin_ttwid:
                # 发送请求获取ttwid
                page = requests.get("https://live.douyin.com/1-2-3-4-5-6-7-8-9-0", timeout=15)
                # 从响应的cookies中获取ttwid并赋值给_douyin_ttwid
                DouyinUtils._douyin_ttwid = page.cookies.get("ttwid")
            # 返回_douyin_ttwid
            return DouyinUtils._douyin_ttwid

    @staticmethod
    def build_request_url(url: str) -> str:
        # 解析url
        parsed_url = urlparse(url)
        # 解析url中的查询参数
        existing_params = parse_qs(parsed_url.query)
        # 添加或修改查询参数
        existing_params['aid'] = ['6383']
        existing_params['device_platform'] = ['web']
        existing_params['browser_language'] = ['zh-CN']
        existing_params['browser_platform'] = ['Win32']
        existing_params['browser_name'] = [DouyinUtils.DOUYIN_USER_AGENT.split('/')[0]]
        existing_params['browser_version'] = [DouyinUtils.DOUYIN_USER_AGENT.split(existing_params['browser_name'][0])[-1][1:]]
        # 编码新的查询字符串
        new_query_string = urlencode(existing_params, doseq=True)
        # 根据解析的url和新的查询字符串构建新的url
        new_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query_string,
            parsed_url.fragment
        ))
        # 返回新的url
        return new_url

