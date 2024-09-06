from threading import Event
from ykdl.common import url_to_module
import yt_dlp

from ..engine.download import DownloadBase
from . import logger


class YDownload(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)
        # 初始化一个空的字典用于存储yt_dlp的选项
        self.ydl_opts = {}

    async def acheck_stream(self, is_check=False):
        try:
            # 调用get_sinfo方法获取流信息
            self.get_sinfo()
            # 如果获取成功，则返回True
            return True
        except yt_dlp.utils.DownloadError:
            # 如果获取失败，则记录日志并返回False
            logger.debug('%s未开播或读取下载信息失败' % self.fname)
            return False

    def get_sinfo(self):
        # 初始化一个空列表用于存储格式ID
        info_list = []
        # 创建一个yt_dlp的实例
        with yt_dlp.YoutubeDL() as ydl:
            if self.url:
                # 如果URL存在，则提取流信息
                info = ydl.extract_info(self.url, download=False)
            else:
                # 如果URL不存在，则记录日志并返回
                logger.debug('%s不存在' % self.__class__.__name__)
                return
            # 遍历提取到的流信息中的格式列表
            for i in info['formats']:
                # 将格式ID添加到info_list列表中
                info_list.append(i['format_id'])
            # 记录info_list列表
            logger.debug(info_list)
        # 返回info_list列表
        return info_list

    def download(self):
        try:
            # 生成下载文件的名称
            filename = self.gen_download_filename(is_fmt=True) + '.' + self.suffix
            # 设置yt_dlp的下载选项，指定输出模板为文件名
            self.ydl_opts = {'outtmpl': filename}
            # 创建一个yt_dlp的实例，并传入下载选项
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                # 调用yt_dlp的download方法下载流
                ydl.download([self.url])
        except yt_dlp.utils.DownloadError:
            # 如果下载失败，则返回1
            return 1
        # 如果下载成功，则返回0
        return 0

class SDownload(DownloadBase):
    def __init__(self, fname, url, suffix='mp4'):
        super().__init__(fname, url, suffix)
        # 初始化流对象
        self.stream = None
        # 初始化事件标志
        self.flag = Event()

    async def acheck_stream(self, is_check=False):
        logger.debug(self.fname)
        import streamlink
        try:
            # 获取流信息
            streams = streamlink.streams(self.url)
            if streams:
                # 获取最优流
                self.stream = streams["best"]
                # 打开流
                fd = self.stream.open()
                # 关闭流
                fd.close()
                # 注意：注释掉的代码不应该出现在此处，因为这样会导致流的关闭，而后续的代码可能还需要使用流对象
                # streams.close()
                # 返回True表示成功检查到流
                return True
        except streamlink.StreamlinkError:
            # 如果出现StreamlinkError异常，则返回None
            return

    def download(self):
        filename = self.gen_download_filename(is_fmt=True) + '.' + self.suffix
        try:
            # 打开流
            with self.stream.open() as fd:
                # 打开文件准备写入
                with open(filename + '.part', 'wb') as file:
                    for f in fd:
                        # 写入文件
                        file.write(f)
                        # 检查事件标志是否设置
                        if self.flag.is_set():
                            # 如果设置了事件标志，则返回1表示下载中断
                            # 注意：注释掉的代码不应该出现在此处，因为这样会清除事件标志，而后续的代码可能还需要检查该标志
                            # self.flag.clear()
                            return 1
                    # 如果循环结束，表示文件下载完成，返回0
                    return 0
        except OSError:
            # 如果出现OSError异常，则重命名文件并抛出异常
            self.download_file_rename(filename + '.part', filename)
            raise

class Generic(DownloadBase):
    def __init__(self, fname, url, suffix='flv'):
        super().__init__(fname, url, suffix)
        # 将自身实例赋值给handler属性
        self.handler = self

    async def acheck_stream(self, is_check=False):
        logger.debug(self.fname)
        try:
            # 解析URL得到对应的站点和URL
            site, url = url_to_module(self.url)
            # 获取URL的解析信息
            info = site.parser(url)
            # 获取第一个流类型
            stream_id = info.stream_types[0]
            # 获取对应流类型的URL列表
            urls = info.streams[stream_id]['src']
            # 将第一个URL赋值给raw_stream_url属性
            self.raw_stream_url = urls[0]
        # 如果出现异常，则执行以下处理
        # print(info.title)
        except:
            # 创建两种下载方式的handler列表
            handlers = [YDownload(self.fname, self.url, 'mp4'), SDownload(self.fname, self.url, 'flv')]
            # 遍历handler列表
            for handler in handlers:
                # 如果当前handler的acheck_stream方法返回True
                if await handler.acheck_stream():
                    # 将当前handler赋值给handler属性
                    self.handler = handler
                    # 将当前handler的suffix赋值给suffix属性
                    self.suffix = handler.suffix
                    # 返回True，表示找到可用的handler
                    return True
            # 如果遍历完handler列表都没有找到可用的handler，则返回False
            return False
        # 如果没有出现异常，则返回True
        return True

    def download(self):
        # 如果handler属性还是自身实例
        if self.handler == self:
            # 则调用父类的download方法
            return super(Generic, self).download()
        # 否则调用handler的download方法
        return self.handler.download()


# 将Generic类赋值给__plugin__变量，用于插件机制
__plugin__ = Generic

