import hashlib
import time
from urllib.parse import parse_qs
from functools import lru_cache

from biliup.common.util import client
from biliup.config import config
from biliup.Danmaku import DanmakuClient
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase
from ..plugins import logger, match1, random_user_agent


@Plugin.download(regexp=r'(?:https?://)?(?:(?:www|m)\.)?douyu\.com')
class Douyu(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        # 调用父类的构造函数，传入文件名、URL和文件后缀
        super().__init__(fname, url, suffix)
        # 从URL中提取房间ID，使用正则表达式匹配'rid=(\d+)'
        self.__room_id = match1(url, r'rid=(\d+)')
        # 获取配置中的'douyu_danmaku'值，默认为False
        self.douyu_danmaku = config.get('douyu_danmaku', False)


    async def acheck_stream(self, is_check=False):
        if len(self.url.split("douyu.com/")) < 2:
            # 如果URL中不包含"douyu.com/"或者只包含一次，则认为是错误的直播间地址
            logger.error(f"{self.plugin_msg}: 直播间地址错误")
            return False

        try:
            if not self.__room_id:
                # 如果__room_id为空，则调用_get_real_rid函数获取真实的房间号
                self.__room_id = _get_real_rid(self.url)
        except:
            # 如果获取房间号出现异常，则记录异常信息并返回False
            logger.exception(f"{self.plugin_msg}: 获取房间号错误")
            return False

        try:
            # 发送HTTP GET请求获取直播间信息
            room_info = (
                await client.get(f"https://www.douyu.com/betard/{self.__room_id}", headers=self.fake_headers)
            ).json()['room']
        except:
            # 如果获取直播间信息出现异常，则记录异常信息并返回False
            logger.exception(f"{self.plugin_msg}: 获取直播间信息错误")
            return False

        if room_info['show_status'] != 1:
            # 如果直播间未开播，则记录日志并返回False
            logger.debug(f"{self.plugin_msg}: 未开播")
            return False
        if room_info['videoLoop'] != 0:
            # 如果直播间正在放录播，则记录日志并返回False
            logger.debug(f"{self.plugin_msg}: 正在放录播")
            return False

        # 如果设置了禁用斗鱼互动游戏，则执行以下逻辑
        if config.get('douyu_disable_interactive_game', False):
            gift_info = (
                await client.get(f"https://www.douyu.com/api/interactive/web/v2/list?rid={self.__room_id}",
                                headers=self.fake_headers)
            ).json().get('data', {})
            if gift_info:
                # 如果存在互动游戏信息，则记录日志并返回False
                logger.debug(f"{self.plugin_msg}: 没有运行互动游戏")
                return False

        # 将直播间标题赋值给self.room_title
        self.room_title = room_info['room_name']


        if is_check:
            try:
                import jsengine
                try:
                    # 尝试调用 jsengine 的 jsengine 方法
                    jsengine.jsengine()
                except jsengine.exceptions.RuntimeError as e:
                    # 如果捕获到 jsengine.exceptions.RuntimeError 异常
                    extra_msg = "如需录制斗鱼直播，"
                    logger.error(f"\n{e}\n{extra_msg}请至少安装一个 Javascript 解释器，如 pip install quickjs")
                    return False
            except:
                # 如果捕获到其他异常
                logger.exception(f"{self.plugin_msg}: ")
                return False
            return True

        try:
            import jsengine
            # 创建 jsengine 的上下文对象
            ctx = jsengine.jsengine()

            # 发送 GET 请求获取加密的 JS 代码
            js_enc = (
                await client.get(f'https://www.douyu.com/swf_api/homeH5Enc?rids={self.__room_id}',
                                 headers=self.fake_headers)
            ).json()['data'][f'room{self.__room_id}']

            # 替换 JS 代码中的 'return eval' 为 'return [strc, vdwdae325w_64we];'
            js_enc = js_enc.replace('return eval', 'return [strc, vdwdae325w_64we];')

            # 在 jsengine 的上下文中执行修改后的 JS 代码，获取签名函数和签名值
            sign_fun, sign_v = ctx.eval(f'{js_enc};ub98484234();')

            # 获取当前时间戳并转换为字符串
            tt = str(int(time.time()))

            # 对时间戳进行 MD5 加密
            did = hashlib.md5(tt.encode('utf-8')).hexdigest()

            # 对房间号、did、时间戳和签名值进行 MD5 加密
            rb = hashlib.md5(f"{self.__room_id}{did}{tt}{sign_v}".encode('utf-8')).hexdigest()

            # 修改签名函数，将 CryptoJS.MD5(cb).toString() 替换为加密后的 rb 值
            sign_fun = sign_fun.rstrip(';').replace("CryptoJS.MD5(cb).toString()", f'"{rb}"')

            # 在签名函数末尾添加房间号、did 和时间戳的调用
            sign_fun += f'("{self.__room_id}","{did}","{tt}");'

            # 在 jsengine 的上下文中执行签名函数，获取参数
            params = parse_qs(ctx.eval(sign_fun))
        except:
            # 如果捕获到异常
            logger.exception(f"{self.plugin_msg}: 获取签名参数异常")
            return False


        # 设置cdn参数，默认为'tct-h5'
        params['cdn'] = config.get('douyucdn', 'tct-h5')
        # 根据配置文件获取douyu_cdn的值，如果未配置则使用之前的cdn值
        params['cdn'] = config.get('douyu_cdn', params['cdn'])
        # 设置rate参数，默认为0
        params['rate'] = config.get('douyu_rate', 0)

        try:
            # 调用get_play_info方法获取直播信息
            live_data = await self.get_play_info(self.__room_id, params)
            # 根据直播信息构建原始流地址
            self.raw_stream_url = f"{live_data['rtmp_url']}/{live_data['rtmp_live']}"
        except:
            # 如果出现异常，记录日志并返回False
            logger.exception(f"{self.plugin_msg}: ")
            return False

        return True


    def danmaku_init(self):
        # 如果启用了斗鱼弹幕功能
        if self.douyu_danmaku:
            # 创建一个字典，用于存储弹幕客户端需要的内容
            content = {
                # 房间号
                'room_id': self.__room_id,
            }
            # 创建弹幕客户端实例，传入URL、生成下载文件名和弹幕内容
            self.danmaku = DanmakuClient(self.url, self.gen_download_filename(), content)

    async def get_play_info(self, room_id, params):
        # 发送POST请求，获取直播信息
        live_data = await client.post(
            f'https://www.douyu.com/lapi/live/getH5Play/{room_id}', headers=self.fake_headers, params=params)
        # 如果请求失败
        if not live_data.is_success:
            # 抛出运行时错误，异常信息为响应的文本内容
            raise RuntimeError(live_data.text)
        # 将响应内容解析为JSON，并获取data字段的值
        live_data = live_data.json().get('data')
        # 如果data是一个字典
        if isinstance(live_data, dict):
            # 如果rtmp_cdn字段不以'h5'结尾或者包含'akm'
            if not live_data['rtmp_cdn'].endswith('h5') or 'akm' in live_data['rtmp_cdn']:
                # 更新params中的cdn字段为cdnsWithName列表中的最后一个元素的cdn字段
                params['cdn'] = live_data['cdnsWithName'][-1]['cdn']
                # 递归调用get_play_info函数，传入相同的room_id和更新后的params
                return await self.get_play_info(room_id, params)
            # 返回直播信息
            return live_data
        # 如果data不是字典，抛出运行时错误，异常信息为live_data
        raise RuntimeError(live_data)


@lru_cache(maxsize=None)
def _get_real_rid(url):
    # 导入requests库
    import requests
    # 设置请求头
    headers = {
        "user-agent": random_user_agent('mobile'),
    }
    # 解析url获取rid
    rid = url.split('douyu.com/')[1].split('/')[0].split('?')[0] or match1(url, r'douyu.com/(\d+)')
    # 发送GET请求获取响应
    resp = requests.get(f"https://m.douyu.com/{rid}", headers=headers)
    # 从响应文本中解析real_rid
    real_rid = match1(resp.text, r'roomInfo":{"rid":(\d+)')
    return real_rid
