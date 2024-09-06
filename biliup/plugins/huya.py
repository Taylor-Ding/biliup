import base64
import hashlib
import json
import random
import time
from urllib.parse import parse_qs, unquote
from functools import lru_cache

from biliup.common.util import client
from biliup.config import config
from biliup.Danmaku import DanmakuClient
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase
from ..plugins import logger, random_user_agent


@Plugin.download(regexp=r'(?:https?://)?(?:(?:www|m)\.)?huya\.com')
class Huya(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        # 调用父类的构造函数，初始化基本属性
        super().__init__(fname, url, suffix)
        # 设置请求头中的referer字段为传入的url
        self.fake_headers['referer'] = url
        # 设置请求头中的cookie字段，从配置中获取huya_cookie的值，默认为空字符串
        self.fake_headers['cookie'] = config.get('user', {}).get('huya_cookie', '')
        # 从url中提取房间ID，假设url的格式为'huya.com/房间ID?...'
        self.__room_id = url.split('huya.com/')[1].split('?')[0]
        # 从配置中获取是否开启虎牙弹幕的选项，默认为False
        self.huya_danmaku = config.get('huya_danmaku', False)


    async def acheck_stream(self, is_check=False):
        try:
            # 如果设置了cookie，则验证cookie
            if self.fake_headers.get('cookie'):
                await self.verify_cookie()

            # 如果房间ID不是数字，则获取真实的房间ID
            if not self.__room_id.isdigit():
                self.__room_id = _get_real_rid(self.url)

            # 获取房间信息
            room_profile = await self.get_room_profile(use_api=True)
        except Exception as e:
            logger.error(f"{self.plugin_msg}: {e}")
            return False

        # 检查房间是否处于直播状态
        if room_profile['realLiveStatus'] != 'ON' or room_profile['liveStatus'] != 'ON':
            '''
            ON: 直播
            REPLAY: 重播
            OFF: 未开播
            '''
            # 如果房间未开播，则记录未开播信息并返回False
            logger.debug(f"{self.plugin_msg} : 未开播")
            self.raw_stream_url = None
            return False

        # 检查主播是否推流
        if not room_profile['liveData'].get('bitRateInfo'):
            # 如果主播未推流，则记录未推流信息并返回False
            # 主播未推流
            logger.debug(f"{self.plugin_msg} : 未推流")
            return False

        # 如果只是检查，则返回True
        if is_check:
            return True

        # 获取最大码率配置
        huya_max_ratio = config.get('huya_max_ratio', 0)
        if huya_max_ratio:
            try:
                # 获取最大码率（不含hdr）
                # 最大码率(不含hdr)
                # max_ratio = html_info['data'][0]['gameLiveInfo']['bitRate']
                max_ratio = room_profile['liveData']['bitRate']

                # 获取可选择的码率列表
                # 可选择的码率
                live_rate_info = json.loads(room_profile['liveData']['bitRateInfo'])

                # 生成码率信息列表
                # 码率信息
                ratio_items = [r.get('iBitRate', 0) if r.get('iBitRate', 0) != 0 else max_ratio for r in live_rate_info]

                # 筛选出符合条件的码率列表
                # 符合条件的码率
                ratio_in_items = [x for x in ratio_items if x <= huya_max_ratio]

                # 确定录制码率
                # 录制码率
                if ratio_in_items:
                    record_ratio = max(ratio_in_items)
                else:
                    record_ratio = max_ratio

            except Exception as e:
                # 在确定码率时发生错误，记录错误信息并返回False
                logger.error(f"{self.plugin_msg}: 在确定码率时发生错误 {e}")
                return False


        # 从配置中获取huyacdn的值，默认为'AL'，该配置项将于0.5.0版本删除
        huya_cdn = config.get('huyacdn', 'AL') # 将于 0.5.0 删除
        # 从配置中获取huya_cdn的值，如果未设置则使用huya_cdn的值，并转换为大写字母
        perf_cdn = config.get('huya_cdn', huya_cdn).upper() # 0.5.0 允许为空字符串以使用 Api 内的 CDN 优先级
        # 根据配置中的huya_protocol的值来确定使用Hls还是Flv协议
        protocol = 'Hls' if config.get('huya_protocol') == 'Hls' else 'Flv'
        # 从配置中获取huya_imgplus的值，默认为True
        allow_imgplus = config.get('huya_imgplus', True)
        # 从配置中获取huya_cdn_fallback的值，默认为False
        cdn_fallback = config.get('huya_cdn_fallback', False)
        # 从配置中获取huya_mobile_api的值，默认为False
        use_api = config.get('huya_mobile_api', False)

        try:
            # 调用get_stream_urls方法获取流链接，并传入协议、是否使用api和是否允许imgplus
            stream_urls = await self.get_stream_urls(protocol, use_api, allow_imgplus)
        except:
            # 如果获取流链接出现异常，则记录异常信息并返回False
            logger.exception(f"{self.plugin_msg}: 没有可用的链接")
            return False

        # 将stream_urls的键转换为列表，作为cdn名称列表
        cdn_name_list = list(stream_urls.keys())
        # 如果perf_cdn为空或者不在cdn_name_list中
        if not perf_cdn or perf_cdn not in cdn_name_list:
            # 记录警告信息，并使用cdn_name_list中的第一个cdn名称作为perf_cdn
            logger.warning(f"{self.plugin_msg}: 使用 {cdn_name_list[0]}")
            perf_cdn = cdn_name_list[0]

        # 虎牙直播流只允许连接一次
        if cdn_fallback:
            # 检查性能最优的CDN链接是否健康
            _url = await self.acheck_url_healthy(stream_urls[perf_cdn])
            if _url is None:
                logger.info(f"{self.plugin_msg}: 提供如下CDN {cdn_name_list}")
                for cdn in cdn_name_list:
                    if cdn == perf_cdn:
                        continue
                    logger.info(f"{self.plugin_msg}: cdn_fallback 尝试 {cdn}")
                    # 检查其他CDN链接是否健康
                    if (await self.acheck_url_healthy(stream_urls[cdn])) is None:
                        continue
                    perf_cdn = cdn
                    logger.info(f"{self.plugin_msg}: CDN 切换为 {perf_cdn}")
                    break
                else:
                    logger.error(f"{self.plugin_msg}: cdn_fallback 所有链接无法使用")
                    return False

            # 重新获取所有CDN链接
            stream_urls = await self.get_stream_urls(protocol, use_api, allow_imgplus)

        # 获取房间标题
        # self.room_title = html_info['data'][0]['gameLiveInfo']['introduction']
        self.room_title = room_profile['liveData']['introduction']
        # 设置原始流链接为性能最优的CDN链接
        self.raw_stream_url = stream_urls[perf_cdn]

        if huya_max_ratio and record_ratio != max_ratio:
            # 如果设置了最大码率且当前码率不等于最大码率，则在链接后添加码率参数
            self.raw_stream_url += f"&ratio={record_ratio}"

        return True



    def danmaku_init(self):
        # 如果开启了虎牙弹幕功能
        if self.huya_danmaku:
            # 初始化弹幕客户端，传入直播链接和生成的下载文件名
            self.danmaku = DanmakuClient(self.url, self.gen_download_filename())


    async def get_room_profile(self, use_api=False) -> dict:
        # 如果使用API获取房间信息
        if use_api:
            # 发起网络请求获取房间信息
            resp = (await client.get(f"https://mp.huya.com/cache.php?m=Live&do=profileRoom&roomid={self.__room_id}", \
                                        headers=self.fake_headers)).json()
            # 如果请求状态不是200，则抛出异常
            if resp['status'] != 200:
                raise Exception(f"{resp['message']}")
            # 返回房间信息数据
            return resp['data']
        else:
            # 发起网络请求获取直播页面的HTML内容
            html = (await client.get(f"https://www.huya.com/{self.__room_id}", headers=self.fake_headers)).text
            # 如果HTML内容中包含"找不到这个主播"，则抛出异常
            if '找不到这个主播' in html:
                raise Exception(f"找不到这个主播")
            # 解析HTML内容获取房间信息，并返回
            return json.loads(html.split('stream: ')[1].split('};')[0])


    async def get_stream_urls(self, protocol, use_api=False, allow_imgplus=True) -> dict:
        '''
        返回指定协议的所有CDN流
        '''
        # 初始化一个空字典用于存储CDN流
        streams = {}
        # 调用get_room_profile方法获取房间信息
        room_profile = await self.get_room_profile(use_api=use_api)

        # 如果不使用API
        if not use_api:
            try:
                # 从房间信息中获取流信息
                stream_info = room_profile['data'][0]['gameStreamInfoList']
            except KeyError:
                raise Exception(f"{room_profile}")
        else:
            # 使用API获取流信息和流比例信息
            stream_info = room_profile['stream']['baseSteamInfoList']
            streams = _dict_sorting(json.loads(room_profile['liveData'].get('mStreamRatioWeb', '{}')))

        # 获取第一个流的信息
        stream = stream_info[0]
        # 获取流的名称
        stream_name = stream['sStreamName']
        # 获取后缀和防盗链参数
        suffix, anti_code = stream[f's{protocol}UrlSuffix'], stream[f's{protocol}AntiCode']

        # 如果不允许imgplus，则将流的名称中的"-imgplus"替换为空字符串
        if not allow_imgplus:
            stream_name = stream_name.replace('-imgplus', '')

        # 构建防盗链参数
        anti_code = self.__build_query(stream_name, anti_code, self.fake_headers['cookie'])

        # 遍历所有的流信息
        for stream in stream_info:
            # 拼接流的URL
            stream_url = f"{stream[f's{protocol}Url']}/{stream_name}.{suffix}?{anti_code}"

            # 如果流的CDN类型不在指定列表中，则跳过
            if stream['sCdnType'] in ['HY', 'HUYA', 'HYZJ']: continue

            # 将CDN类型和对应的流URL存储到streams字典中
            streams[stream['sCdnType']] = stream_url

        # 返回存储CDN流的字典
        return streams


    @staticmethod
    def __build_query(stream_name, anti_code, cookies=None) -> str:
        # 解析anti_code中的查询参数
        url_query = parse_qs(anti_code)

        # 获取platform_id，默认值为100
        # 如果url_query中包含't'参数，则使用其值作为platform_id，否则使用默认值100
        # platform_id = 100
        platform_id = url_query.get('t', [100])[0]

        # 获取用户id
        uid = _get_uid(cookies, stream_name)

        # 对用户id进行位运算并取低32位
        convert_uid = (uid << 8 | uid >> (32 - 8)) & 0xFFFFFFFF

        # 获取ws_time
        ws_time = url_query['wsTime'][0]

        # 计算ct
        ct = int((int(ws_time, 16) + random.random()) * 1000)

        # 计算seq_id
        seq_id = uid + int(time.time() * 1000)

        # 对url_query中的'fm'参数进行base64解码和解码，并取第一个'_'之前的部分作为ws_secret_prefix
        ws_secret_prefix = base64.b64decode(unquote(url_query['fm'][0]).encode()).decode().split('_')[0]

        # 根据seq_id、url_query中的'ctype'参数和platform_id计算ws_secret_hash
        ws_secret_hash = hashlib.md5(f"{seq_id}|{url_query['ctype'][0]}|{platform_id}".encode()).hexdigest()

        # 根据ws_secret_prefix、convert_uid、stream_name、ws_secret_hash和ws_time计算ws_secret
        ws_secret = hashlib.md5(f'{ws_secret_prefix}_{convert_uid}_{stream_name}_{ws_secret_hash}_{ws_time}'.encode()).hexdigest()

        # 以下为被注释掉的代码块，用于生成查询字符串，但当前代码中未使用
        # &codec=av1
        # &codec=264
        # &codec=265
        # dMod: wcs-25 浏览器解码信息
        # sdkPcdn: 1_1 第一个1连接次数 第二个1是因为什么连接
        # t: 平台信息 100 web(ctype=huya_live) 102 小程序(ctype=tars_mp)
        # sv: 2401090219 版本
        # sdk_sid:  _sessionId sdkInRoomTs 当前毫秒时间

        # 构造anti_code字典
        anti_code = {
            "wsSecret": ws_secret,
            "wsTime": ws_time,
            "seqid": str(seq_id),
            "ctype": url_query['ctype'][0],
            "fs": url_query['fs'][0],
            "u": convert_uid,
            "t": platform_id,
            "ver": "1",
            "uuid": str(int((ct % 1e10 + random.random()) * 1e3 % 0xffffffff)),
            "sdk_sid": str(int(time.time() * 1000)),
            "codec": "264",
        }

        # 将anti_code字典转换为查询字符串并返回
        return '&'.join([f"{k}={v}" for k, v in anti_code.items()])



    async def verify_cookie(self):
        # 如果fake_headers中的cookie字段存在
        if self.fake_headers['cookie']:
            # 发送POST请求到指定URL，验证cookie的有效性
            resp = (await client.post('https://udblgn.huya.com/web/cookie/verify', \
                                    headers=self.fake_headers, data={'appId': 5002})).json()
            # 如果返回结果中的returnCode不等于0，表示cookie验证失败
            if resp.json()['returnCode'] != 0:
                # 打印错误信息
                logger.error(f"{self.plugin_msg}: {resp.json()['message']}")
                # 清空fake_headers中的cookie字段
                self.fake_headers['cookie'] = ''


@lru_cache(maxsize=None)
def _get_real_rid(url):
    import requests
    # 设置请求头
    headers = {
        'user-agent': random_user_agent(),
    }
    # 发送请求获取页面内容
    html = requests.get(url, headers=headers).text
    # 判断页面内容中是否包含"找不到这个主播"
    if '找不到这个主播' in html:
        # 如果包含，则抛出异常
        raise Exception(f"找不到这个主播")
    # 截取页面内容中的json数据
    html_obj = json.loads(html.split('stream: ')[1].split('};')[0])
    # 返回主播的房间号
    return str(html_obj['data'][0]['gameLiveInfo']['profileRoom'])


def _dict_sorting(data: dict) -> dict:
    if data:
        # 过滤掉不需要的键
        data = {k: v for k, v in data.items() if k not in ['HY', 'HUYA', 'HYZJ']}
        # 对字典进行排序，按照值从大到小排序
        return dict(sorted(data.items(), key=lambda x: x[1], reverse=True))
    return {}



def _get_uid(cookie: str, stream_name: str) -> int:
    # 如果cookie存在
    if cookie:
        # 将cookie字符串解析为字典形式
        cookie_dict = {k.strip(): v for k, v in (item.split('=') for item in cookie.split(';'))}
        # 遍历['udb_uid', 'yyuid']这两个键
        for key in ['udb_uid', 'yyuid']:
            # 如果键在cookie_dict中存在
            if key in cookie_dict:
                # 返回键对应的值转换为整数
                return int(cookie_dict[key])
    # 如果stream_name存在
    if stream_name:
        # 返回stream_name按'-'分割后的第一个元素转换为整数
        return int(stream_name.split('-')[0])
    # 如果以上条件都不满足，则返回一个随机整数
    return random.randint(1400000000000, 1499999999999)

