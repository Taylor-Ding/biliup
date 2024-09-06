import biliup.common.util
from ..common import tools
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase
from ..plugins import logger, match1


@Plugin.download(regexp=r'(?:https?://)?www\.flextv\.co\.kr')
class FlexTvCoKr(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        # 调用父类的构造函数
        super().__init__(fname, url, suffix)

    async def acheck_stream(self, is_check=False):
        # 从url中提取房间号
        room_id = match1(self.url, r"/channels/(\d+)/live")
        if not room_id:
            # 如果房间号不存在，则记录警告日志
            logger.warning(f"{FlexTvCoKr.__name__}: {self.url}: 直播间地址错误")
        # 发送请求获取直播流信息
        response = await biliup.common.util.client.get(f"https://api.flextv.co.kr/api/channels/{room_id}/stream?option=all",
                                                       timeout=5,
                                                      headers=self.fake_headers)
        if response.status_code != 200:
            # 如果请求失败，则根据不同状态码记录日志并返回False
            if response.status_code == 400:
                logger.debug(f"{FlexTvCoKr.__name__}: {self.url}: 未开播或直播间不存在")
                return False
            else:
                logger.warning(f"{FlexTvCoKr.__name__}: {self.url}: 获取错误，本次跳过")
                return False

        # 解析响应内容，获取房间信息
        room_info = response.json()
        # 设置房间标题和封面URL
        self.room_title = room_info['title']
        self.live_cover_url = room_info['thumbUrl']
        if is_check:
            # 如果只是检查，则返回True
            return True

        # 发送请求获取m3u8文件内容
        m3u8_content = (await biliup.common.util.client.get(room_info['sources'][0]['url'], timeout=5, headers=self.fake_headers)).text
        import m3u8
        # 解析m3u8文件内容
        m3u8_obj = m3u8.loads(m3u8_content)
        if m3u8_obj.is_variant:
            # 如果m3u8文件包含多个码率的流，则取码率最大的流
            # 取码率最大的流
            max_ratio_stream = max(m3u8_obj.playlists, key=lambda x: x.stream_info.bandwidth)
            self.raw_stream_url = max_ratio_stream.uri
        else:
            # 如果解析失败，则记录警告日志
            logger.warning(f"{FlexTvCoKr.__name__}: {self.url}: 解析错误")
            return False

        return True

# 注意：代码中的最后一部分存在逻辑错误，因为无论前面是否返回了False，最后的return True都会被执行，导致函数始终返回True。
# 正确的代码应该是将最后的return True删除，这样函数会根据前面的逻辑正确返回True或False。


