import biliup.common.util
from ..common import tools
from ..engine.decorators import Plugin
from ..engine.download import DownloadBase
from ..plugins import logger

@Plugin.download(regexp=r'(?:https?://)?www\.bigo\.tv')
class Bigo(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)

    async def acheck_stream(self, is_check=False):
        try:
            # 获取直播间的ID
            room_id = self.url.split('/')[-1].split('?')[0]
        except:
            # 如果获取直播间ID失败，则输出警告并返回False
            logger.warning(f"{Bigo.__name__}: {self.url}: 直播间地址错误")
            return False

        try:
            # 发送POST请求获取直播间的信息
            room_info = (await biliup.common.util.client.post(f'https://ta.bigo.tv/official_website/studio/getInternalStudioInfo', timeout=10,
                                                             headers={**self.fake_headers, 'Accept': 'application/json'},
                                                             data={"siteId": room_id})).json()

            # 如果获取直播间信息失败，则抛出异常
            if room_info['code'] != 0:
                raise
        except:
            # 如果获取直播间信息出错，则输出警告并返回False
            logger.warning(f"{Bigo.__name__}: {self.url}: 获取错误，本次跳过")
            return False

        try:
            # 判断直播间是否存在
            if room_info['data']['alive'] is None:
                logger.warning(f"{Bigo.__name__}: {self.url}: 直播间不存在")
                return False

            # 判断直播间是否开播，并且是否有直播流地址
            if room_info['data']['alive'] != 1 or not room_info['data']['hls_src']:
                logger.debug(f"{Bigo.__name__}: {self.url}: 直播间未开播")
                return False

            # 设置直播流地址和直播间标题
            self.raw_stream_url = room_info['data']['hls_src']
            self.room_title = room_info['data']['roomTopic']
        except:
            # 如果解析直播间信息出错，则输出警告并返回False
            logger.warning(f"{Bigo.__name__}: {self.url}: 解析错误")
            return False

        # 返回True，表示检测成功
        return True

