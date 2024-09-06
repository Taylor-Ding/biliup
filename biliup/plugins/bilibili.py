import time
import json
import re

from biliup.common.util import client
from biliup.config import config
from . import match1, logger
from biliup.Danmaku import DanmakuClient
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase


OFFICIAL_API = "https://api.live.bilibili.com"

@Plugin.download(regexp=r'(?:https?://)?(b23\.tv|live\.bilibili\.com)')
class Bililive(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        # 调用父类的初始化方法
        super().__init__(fname, url, suffix)
        # 初始化直播时长为0
        self.live_time = 0
        # 获取配置文件中的bilibili_danmaku设置
        self.bilibili_danmaku = config.get('bilibili_danmaku', False)
        # 设置fake_headers中的referer字段为传入的url
        self.fake_headers['referer'] = url
        # 如果配置文件中存在用户信息，并且包含bili_cookie字段
        if config.get('user', {}).get('bili_cookie'):
            # 将bili_cookie设置为fake_headers中的cookie字段
            self.fake_headers['cookie'] = config.get('user', {}).get('bili_cookie')
        # 如果配置文件中存在用户信息，并且包含bili_cookie_file字段
        if config.get('user', {}).get('bili_cookie_file'):
            # 获取cookie文件的名称
            cookie_file_name = config.get('user', {}).get('bili_cookie_file')
            try:
                # 打开cookie文件并读取内容
                with open(cookie_file_name, encoding='utf-8') as stream:
                    # 解析json格式的cookie文件内容
                    cookies = json.load(stream)["cookie_info"]["cookies"]
                    # 初始化cookies_str为空字符串
                    cookies_str = ''
                    # 遍历cookies列表，拼接成cookie字符串
                    for i in cookies:
                        cookies_str += f"{i['name']}={i['value']};"
                    # 将拼接好的cookie字符串设置为fake_headers中的cookie字段
                    self.fake_headers['cookie'] = cookies_str
            # 如果在读取或解析cookie文件时出现异常
            except Exception:
                # 记录异常日志
                logger.exception("load_cookies error")

        # else:
        #    logger.warning("No cookie provided. The original quality may not be available.")

    async def acheck_stream(self, is_check=False):

        client.headers.update(self.fake_headers)

        # 如果链接中包含"b23.tv"
        if "b23.tv" in self.url:
            try:
                # 发送GET请求，获取响应，并且不跟随重定向
                resp = await client.get(self.url, follow_redirects=False)
                # 如果响应状态码不是301或302
                if resp.status_code not in {301, 302}:
                    # 抛出异常
                    raise
                # 获取重定向后的URL
                url = str(resp.next_request.url)
                # 如果URL中不包含"live.bilibili"
                if "live.bilibili" not in url:
                    # 抛出异常
                    raise
                # 更新URL
                self.url = url
            except:
                # 记录错误日志，表示不支持的链接
                logger.error(f"{self.plugin_msg}: 不支持的链接")
                return False

        # 从URL中匹配出房间号
        room_id = match1(self.url, r'bilibili.com/(\d+)')
        # 获取配置中的bili_qn值，并转换为整数
        qualityNumber = int(config.get('bili_qn', 10000))

        # 构造请求URL
        # 获取直播状态与房间标题
        info_by_room_url = f"{OFFICIAL_API}/xlive/web-room/v1/index/getInfoByRoom?room_id={room_id}"
        try:
            # 发送GET请求，获取房间信息，并解析为JSON格式
            room_info = (await client.get(info_by_room_url)).json()
        except:
            # 记录异常日志
            logger.exception(f"{self.plugin_msg}: ")
            return False
        # 如果房间信息中的code不等于0
        if room_info['code'] != 0:
            # 记录错误日志，并输出房间信息
            logger.error(f"{self.plugin_msg}: {room_info}")
            return False
        # 如果房间信息中的直播状态不等于1（表示未开播）
        if room_info['data']['room_info']['live_status'] != 1:
            # 记录调试日志，表示未开播
            logger.debug(f"{self.plugin_msg}: 未开播")
            # 原始流URL为空
            self.raw_stream_url = None
            return False
        # 更新直播封面URL
        self.live_cover_url = room_info['data']['room_info']['cover']
        # 获取直播开始时间
        live_start_time = room_info['data']['room_info']['live_start_time']
        # 允许分段时更新标题
        # 更新房间标题
        self.room_title = room_info['data']['room_info']['title']
        # 如果直播开始时间大于当前直播时间
        if live_start_time > self.live_time:
            # 更新直播时间
            self.live_time = live_start_time
            # 设置is_new_live为True，表示是新直播
            is_new_live = True
        else:
            # 设置is_new_live为False，表示不是新直播
            is_new_live = False

        if is_check:
            # 发送GET请求获取B站导航数据
            _res = await client.get('https://api.bilibili.com/x/web-interface/nav')
            try:
                # 解析返回的JSON数据，并获取用户数据
                user_data = json.loads(_res.text).get('data')
                if user_data.get('isLogin'):
                    # 如果用户已登录，记录用户名、mid和登录状态
                    logger.info(f"用户名：{user_data['uname']}, mid：{user_data['mid']}, isLogin：{user_data['isLogin']}")
                else:
                    # 如果用户未登录，记录警告信息
                    logger.warning(f"{self.plugin_msg}: 未登录，或将只能录制到最低画质。")
            except:
                # 如果解析或获取用户数据发生异常，记录异常信息
                logger.exception(f"{self.plugin_msg}: 登录态校验失败 {_res.text}")
            return True

        # 从配置中获取相关参数
        protocol = config.get('bili_protocol', 'stream')
        perf_cdn = config.get('bili_perfCDN')
        cdn_fallback = config.get('bili_cdn_fallback', False)
        force_source = config.get('bili_force_source', False)
        main_api = config.get('bili_liveapi', OFFICIAL_API).rstrip('/')
        fallback_api = config.get('bili_fallback_api', OFFICIAL_API).rstrip('/')
        cn01_sids = config.get('bili_replace_cn01', [])
        if isinstance(cn01_sids, str):
            cn01_sids = cn01_sids.split(',')
        normalize_cn204 = config.get('bili_normalize_cn204', False)

        # 构造请求参数
        params = {
            # 房间ID
            'room_id': room_id,
            # 协议类型：0为http_stream，1为http_hls
            'protocol': '0,1',  # 0: http_stream, 1: http_hls
            # 格式类型：0为flv，1为ts，2为fmp4
            'format': '0,1,2',  # 0: flv, 1: ts, 2: fmp4
            # 编码类型：0为avc，1为hevc，2为av1
            'codec': '0',  # 0: avc, 1: hevc, 2: av1
            # 画质等级
            'qn': qualityNumber,
            # 平台类型：web、html5、android、ios
            'platform': 'html5',  # web, html5, android, ios
            # 'ptype': '8',
            # Dolby音效设置
            'dolby': '5',
            # 全景设置（不支持html5）
            # 'panorama': '1' # 全景(不支持 html5)
        }


        if self.raw_stream_url is not None \
                and qualityNumber >= 10000 \
                and not is_new_live:
            # 如果原始流地址不为空，且画质等级大于等于10000，且不是新直播
            # 同一个 streamName 即可复用，除非被超管切断
            # 前面拿不到 streamName，目前使用开播时间判断
            url = await self.acheck_url_healthy(self.raw_stream_url)
            if url is not None:
                # 调用 acheck_url_healthy 方法检查原始流地址是否健康
                # 如果健康，则记录日志并返回 True
                logger.debug(f"{self.plugin_msg}: 复用 {url}")
                return True
            else:
                # 如果不健康，则将原始流地址置为空
                self.raw_stream_url = None

        try:
            # 尝试从主 API 获取播放信息
            play_info = await self._get_play_info(main_api, params)
            if not play_info or check_areablock(play_info):
                # 如果播放信息为空或被地区封锁
                logger.debug(f"{self.plugin_msg}: {main_api} 返回 {play_info}")
                # 则从备用 API 获取播放信息
                play_info = await self._get_play_info(fallback_api, params)
                if not play_info or check_areablock(play_info):
                    # 如果播放信息仍然为空或被地区封锁
                    logger.debug(f"{self.plugin_msg}: {fallback_api} 返回 {play_info}")
                    # 则记录日志并返回 False
                    return False
        except Exception:
            # 如果发生异常
            logger.exception(f"{self.plugin_msg}: ")
            # 则记录异常并返回 False
            return False
        if play_info['code'] != 0:
            # 如果播放信息的 code 不为 0
            logger.error(f"{self.plugin_msg}: {play_info}")
            # 则记录错误日志并返回 False
            return False


        # 获取流信息列表
        streams = play_info['data']['playurl_info']['playurl']['stream']

        # 根据协议选择流
        stream = streams[1] if protocol.startswith('hls') and len(streams) > 1 else streams[0]

        # 获取流的格式
        stream_format = stream['format'][0]

        # 如果协议为 hls_fmp4
        if protocol == "hls_fmp4":
            # 如果流的格式不是 fmp4
            if stream_format['format_name'] != 'fmp4':
                # 如果流的格式列表中有多个格式
                if len(stream['format']) > 1:
                    # 选择第二个格式
                    stream_format = stream['format'][1]
                # 如果流的格式列表中只有一个格式，且当前时间与直播开始时间之差小于等于60秒
                elif int(time.time()) - live_start_time <= 60:
                    # 输出警告信息：暂时未提供 hls_fmp4 流，等待下一次检测
                    logger.warning(f"{self.plugin_msg}: 暂时未提供 hls_fmp4 流，等待下一次检测")
                    return False
                else:
                    # 回退到第一个流的第一个格式
                    # hls_ts 大抵是无了，只能回退 Flv
                    stream_format = streams[0]['format'][0]
                    logger.info(f"{self.plugin_msg}: 已切换为 stream 流")

        # 获取流的编解码信息
        stream_info = stream_format['codec'][0]

        # 如果画质等级为 10000
        # 且画质等级不在流的接受画质等级列表中
        # 且当前流的协议名称与第一个流的协议名称不同
        # 防止 hls_fmp4 不转码原画
        if qualityNumber == 10000 \
            and qualityNumber not in stream_info['accept_qn'] \
            and stream['protocol_name'] != streams[0]['protocol_name']:
            # 切换到第一个流的编解码信息
            stream_info = streams[0]['format'][0]['codec'][0]
            # 输出警告信息：当前 protocol-xxx 未提供原画，尝试回退到 stream 流
            logger.warning(
                f"{self.plugin_msg}: 当前 protocol-{protocol} 未提供原画，尝试回退到 stream 流"
            )

        # 构造流地址
        stream_url = {
            'base_url': stream_info['base_url'],
        }

        if perf_cdn is not None:
            # 将 perf_cdn 字符串按照逗号分隔成列表
            perf_cdn_list = perf_cdn.split(',')
            for url_info in stream_info['url_info']:
                # 如果 stream_url 中已经存在 'host' 键，则跳出循环
                if 'host' in stream_url:
                    break
                for cdn in perf_cdn_list:
                    # 如果 cdn 存在于 url_info 的 'extra' 中
                    if cdn in url_info['extra']:
                        # 将 url_info 中的 'host' 和 'extra' 赋值给 stream_url
                        stream_url['host'] = url_info['host']
                        stream_url['extra'] = url_info['extra']
                        # 记录日志，输出找到的 host
                        logger.debug(f"Found {stream_url['host']}")
                        break

        # 如果 stream_url 的长度小于 3
        if len(stream_url) < 3:
            # 将 stream_info['url_info'] 列表中最后一个元素的 'host' 和 'extra' 赋值给 stream_url
            stream_url['host'] = stream_info['url_info'][-1]['host']
            stream_url['extra'] = stream_info['url_info'][-1]['extra']

        # 移除 streamName 内画质标签
        if force_source:
            # 匹配 streamName 的正则表达式
            streamname_regexp = r"(live_\d+_\w+_\w+_?\w+?)"  # 匹配 streamName
            # 使用正则表达式在 stream_url['base_url'] 中查找 streamName
            streamName = match1(stream_url['base_url'], streamname_regexp)
            # 如果找到了 streamName 并且 qualityNumber 大于等于 10000
            if streamName is not None and qualityNumber >= 10000:
                # 替换 stream_url['base_url'] 中的画质标签
                _base_url = stream_url['base_url'].replace(f"_{streamName.split('_')[-1]}", '')
                # 检查替换后的 URL 是否健康
                if (await self.acheck_url_healthy(f"{stream_url['host']}{_base_url}{stream_url['extra']}")) is not None:
                    # 如果健康，则将替换后的 URL 赋值给 stream_url['base_url']
                    stream_url['base_url'] = _base_url
                else:
                    # 记录日志，输出 force_source 失败的情况
                    logger.debug(f"{self.plugin_msg}: force_source {_base_url}")

        # 如果 cn01_sids 不为空
        if cn01_sids:
            # 如果 stream_url['extra'] 中包含 "cn-gotcha01"
            if "cn-gotcha01" in stream_url['extra']:
                for sid in cn01_sids:
                    # 构造新的 host
                    _host = f"https://{sid}.bilivideo.com"
                    # 构造新的 URL
                    url = f"{_host}{stream_url['base_url']}{stream_url['extra']}"
                    # 检查新的 URL 是否健康
                    if (await self.acheck_url_healthy(url)) is not None:
                        # 如果健康，则将新的 host 赋值给 stream_url['host']，并跳出循环
                        stream_url['host'] = _host
                        break
                    else:
                        # 记录日志，输出 sid 不可用的情况
                        logger.debug(f"{self.plugin_msg}: {sid} is not available")

        # 拼接得到最终的原始流地址
        self.raw_stream_url = f"{stream_url['host']}{stream_url['base_url']}{stream_url['extra']}"

        if normalize_cn204:
            # 如果需要规范化cn204
            # 替换self.raw_stream_url中"(?<=cn-gotcha204)-[1-4]"为""，最多替换一次
            self.raw_stream_url = re.sub(r"(?<=cn-gotcha204)-[1-4]", "", self.raw_stream_url, 1)

        if cdn_fallback:
            # 如果需要CDN回退
            _url = await self.acheck_url_healthy(self.raw_stream_url)
            if _url is None:
                # 如果检查到的URL无效
                i = len(stream_info['url_info'])
                while i:
                    i -= 1
                    try:
                        # 尝试使用stream_info['url_info']中的其他URL
                        self.raw_stream_url = "{}{}{}".format(stream_info['url_info'][i]['host'],
                                                             stream_url['base_url'],
                                                              stream_info['url_info'][i]['extra'])
                        _url = await self.acheck_url_healthy(self.raw_stream_url)
                        if _url is not None:
                            # 如果新的URL有效
                            self.raw_stream_url = _url
                            break
                    except:
                        # 如果发生异常
                        logger.exception("Uncaught exception:")
                        continue
                    finally:
                        # 记录当前尝试的URL
                        logger.debug(f"{i} - {self.raw_stream_url}")
                else:
                    # 如果所有URL都无效
                    logger.debug(play_info)
                    self.raw_stream_url = None
                    return False
            else:
                # 如果检查到的URL有效
                self.raw_stream_url = _url

        return True


    def danmaku_init(self):
        # 如果启用了Bilibili弹幕
        if self.bilibili_danmaku:
            # 创建一个弹幕客户端实例，传入URL和生成的文件名
            self.danmaku = DanmakuClient(self.url, self.gen_download_filename())


    async def _get_play_info(self, api, params) -> dict:
        # 判断api是否以http://或https://开头，如果不是则添加http://前缀
        api = (lambda a: a if a.startswith(('http://', 'https://')) else 'http://' + a)(api)
        # 拼接完整的URL
        full_url = f"{api}/xlive/web-room/v2/index/getRoomPlayInfo"
        try:
            # 发送GET请求获取播放信息
            _info = await client.get(full_url, params=params)
            # 将返回的文本解析为JSON格式并返回
            return json.loads(_info.text)
        except:
            # 记录异常信息并打印错误信息
            logger.exception(f"{params['room_id']} <- {api} 返回内容错误: {_info.text}")
        return {}



# Copy from room-player.js
def check_areablock(data):
    '''
    :return: True if area block
    '''
    # 如果播放链接为空
    if not data['data']['playurl_info']['playurl']:
        # 记录错误日志：Sorry, bilibili is currently not available in your country according to copyright restrictions.
        logger.error('Sorry, bilibili is currently not available in your country according to copyright restrictions.')
        # 记录错误日志：非常抱歉，根据版权方要求，您所在的地区无法观看本直播
        logger.error('非常抱歉，根据版权方要求，您所在的地区无法观看本直播')
        # 返回True，表示地区受限
        return True
    # 返回False，表示地区不受限
    return False

