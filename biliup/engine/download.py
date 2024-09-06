import asyncio
import logging
import os
import re
import subprocess
import threading
import time
import shutil
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Callable, Optional
from urllib.parse import urlparse

import requests
from requests.utils import DEFAULT_ACCEPT_ENCODING
from httpx import HTTPStatusError

from biliup.common.util import client, loop
from biliup.database.db import add_stream_info, SessionLocal, update_cover_path, update_room_title, update_file_list
from biliup.plugins import random_user_agent
import stream_gears
from PIL import Image

from biliup.config import config
from biliup.Danmaku import IDanmakuClient

logger = logging.getLogger('biliup')


class DownloadBase(ABC):
    def __init__(self, fname, url, suffix=None, opt_args=None):
        self.room_title = None
        if opt_args is None:
            opt_args = []
        self.fname = fname
        self.url = url
        # 录制后保存文件格式而非源流格式 对应原配置文件format 仅ffmpeg及streamlink生效
        if not suffix:
            logger.error(f'检测到suffix不存在，请补充后缀')
        else:
            self.suffix = suffix.lower()
        self.live_cover_path = None
        self.database_row_id = 0
        self.downloader = config.get('downloader', 'stream-gears')
        # ffmpeg.exe -i  http://vfile1.grtn.cn/2018/1542/0254/3368/154202543368.ssm/154202543368.m3u8
        # -c copy -bsf:a aac_adtstoasc -movflags +faststart output.mp4
        self.raw_stream_url = None

        # 主播单独传参会覆盖全局设置。例如新增了一个全局的filename_prefix参数，在下面添加self.filename_prefix = config.get('filename_prefix'),
        # 即可通过self.filename_prefix在下载或者上传时候传递主播单独的设置参数用于调用（如果该主播有设置单独参数，将会优先使用单独参数；如无，则会优先你用全局参数。）
        self.filename_prefix = config.get('filename_prefix')
        self.use_live_cover = config.get('use_live_cover', False)
        self.opt_args = opt_args
        self.live_cover_url = None
        self.fake_headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-encoding': DEFAULT_ACCEPT_ENCODING,
            'accept-language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
            'user-agent': random_user_agent(),
        }
        self.segment_time = config.get('segment_time', '01:00:00')
        self.file_size = config.get('file_size')

        # 是否是下载模式 跳过下播检测
        self.is_download = False

        # 分段后处理
        self.segment_processor = config.get('segment_processor')
        self.segment_processor_thread = []
        # 分段后处理并行
        self.segment_processor_parallel = config.get('segment_processor_parallel', False)

        # 弹幕客户端
        self.danmaku: Optional[IDanmakuClient] = None

        self.plugin_msg = f"{self.__class__.__name__} - {url}"

    @abstractmethod
    async def acheck_stream(self, is_check=False):
        # is_check 是否是检测模式 检测模式可以忽略只有下载时需要的耗时操作
        raise NotImplementedError()

    def download(self):
        logger.info(f"{self.plugin_msg}: Start downloading {self.raw_stream_url}")
        if self.is_download:
            # 检查是否安装了FFMpeg
            if not shutil.which("ffmpeg"):
                # 如果未安装，则记录错误日志
                logger.error("未安装 FFMpeg 或不存在于 PATH 内")
                # 打印当前用户的PATH环境变量
                logger.debug("Current user's PATH is:" + os.getenv("PATH"))
                return False
            else:
                # 调用FFMpeg分段下载方法
                return self.ffmpeg_segment_download()

        # 解析原始流URL的路径部分
        parsed_url_path = urlparse(self.raw_stream_url).path
        if self.downloader == 'streamlink' or self.downloader == 'ffmpeg':
            # 检查是否安装了FFMpeg
            if shutil.which("ffmpeg"):
                # streamlink无法处理flv,所以回退到ffmpeg
                if self.downloader == 'streamlink' and '.flv' not in parsed_url_path:
                    return self.ffmpeg_download(use_streamlink=True)
                else:
                    return self.ffmpeg_download()
            else:
                # 如果未安装FFMpeg，则记录错误日志，并使用stream-gears进行下载
                logger.error("未安装 FFMpeg 或不存在于 PATH 内，本次下载使用 stream-gears")
                logger.debug("Current user's PATH is:" + os.getenv("PATH"))

        # 根据URL路径判断流的类型
        if '.flv' in parsed_url_path:
            # 假定是flv流
            self.suffix = 'flv'
        else:
            # 其他流使用stream-gears按hls保存为ts
            self.suffix = 'ts'

        # 调用stream-gears进行下载
        stream_gears_download(self.raw_stream_url, self.fake_headers, self.gen_download_filename(),
                              self.segment_time,
                             self.file_size,
                              lambda file_name: self.__download_segment_callback(file_name))
        return True


    def ffmpeg_segment_download(self):
        # 初始化输入参数列表，添加日志级别和覆盖选项
        # TODO 无日志
        # , '-report'
        # ffmpeg 输入参数
        input_args = [
            '-loglevel', 'quiet', '-y'
        ]
        # 初始化输出参数列表，添加比特流过滤器
        # ffmpeg 输出参数
        output_args = [
            '-bsf:a', 'aac_adtstoasc'
        ]
        # 添加伪头部信息和读取超时选项到输入参数列表
        input_args += ['-headers', ''.join('%s: %s\r\n' % x for x in self.fake_headers.items()),
                       '-rw_timeout', '20000000']
        # 如果URL路径中包含'.m3u8'，则添加最大重载选项到输入参数列表
        if '.m3u8' in urlparse(self.raw_stream_url).path:
            input_args += ['-max_reload', '1000']

        # 添加输入流选项到输入参数列表
        input_args += ['-i', self.raw_stream_url]

        # 添加输出格式和选项到输出参数列表
        output_args += ['-f', 'segment']
        # output_args += ['-segment_format', self.suffix]
        # 添加分段列表选项到输出参数列表
        output_args += ['-segment_list', 'pipe:1']
        # 设置分段列表类型为flat
        output_args += ['-segment_list_type', 'flat']
        # 重置时间戳
        output_args += ['-reset_timestamps', '1']
        # output_args += ['-strftime', '1']
        # 如果设置了分段时间，则添加到输出参数列表
        if self.segment_time:
            output_args += ['-segment_time', self.segment_time]
        else:
            # 如果没有设置分段时间，则使用默认的超长分段时间以避免适配两套时间格式
            # 避免适配两套
            output_args += ['-segment_time', '9999:00:00']

        # 复制原始流，不重新编码
        output_args += ['-c', 'copy']
        # 添加其他选项到输出参数列表
        output_args += self.opt_args

        # 生成下载文件名
        file_name = self.gen_download_filename(is_fmt=True)

        # 构造ffmpeg命令行参数列表
        args = ['ffmpeg', *input_args, *output_args, f'{file_name}_%d.{self.suffix}']

        # 调用subprocess执行ffmpeg命令，并处理输出
        with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as proc:
            for line in iter(proc.stdout.readline, b''):  # b'\n'-separated lines
                try:
                    # 读取ffmpeg输出中的文件名，并进行解码
                    ffmpeg_file_name = line.rstrip().decode(errors='ignore')
                    # 暂停一段时间，避免过快地重命名文件
                    time.sleep(1)
                    # 文件重命名
                    self.download_file_rename(ffmpeg_file_name, f'{file_name}.{self.suffix}')
                    # 调用回调函数处理重命名后的文件
                    self.__download_segment_callback(f'{file_name}.{self.suffix}')
                    # 生成新的下载文件名
                    file_name = self.gen_download_filename(is_fmt=True)
                except:
                    # 记录异常日志
                    logger.error(f'分段事件失败：{self.__class__.__name__} - {self.fname}', exc_info=True)

        # 返回ffmpeg命令的返回值是否为0，表示是否执行成功
        return proc.returncode == 0


    def ffmpeg_download(self, use_streamlink=False):
        # 初始化streamlink进程
        # streamlink进程
        streamlink_proc = None
        # updatedFileList = False
        try:
            # 生成文件名（不含后缀）
            # 文件名不含后戳
            fmt_file_name = self.gen_download_filename(is_fmt=True)
            # 初始化ffmpeg输入参数列表
            # ffmpeg 输入参数
            input_args = []
            # 初始化ffmpeg输出参数列表
            # ffmpeg 输出参数
            output_args = []
            if use_streamlink:
                # 构造streamlink命令
                streamlink_cmd = [
                    'streamlink',
                    '--stream-segment-threads', '3',
                    '--hls-playlist-reload-attempts', '1',
                    '--http-header',
                    ';'.join([f'{key}={value}' for key, value in self.fake_headers.items()]),
                    self.raw_stream_url,
                    'best',
                    '-O'
                ]
                # 执行streamlink命令，并将输出重定向到管道
                streamlink_proc = subprocess.Popen(streamlink_cmd, stdout=subprocess.PIPE)
                # 设置ffmpeg的输入为管道
                input_uri = 'pipe:0'
            else:
                # 添加ffmpeg的输入参数
                input_args += ['-headers', ''.join('%s: %s\r\n' % x for x in self.fake_headers.items()),
                               '-rw_timeout', '20000000']
                # 如果原始流URL的路径中包含'.m3u8'，则添加相应的参数
                if '.m3u8' in urlparse(self.raw_stream_url).path:
                    input_args += ['-max_reload', '1000']
                # 设置ffmpeg的输入为原始流URL
                input_uri = self.raw_stream_url

            # 添加ffmpeg的输入URI参数
            input_args += ['-i', input_uri]


            if self.segment_time:
                # 如果设置了分段时间，则添加-to参数
                output_args += ['-to', self.segment_time]
            if self.file_size:
                # 如果设置了文件大小，则添加-fs参数
                output_args += ['-fs', str(self.file_size)]

            # 添加其他可选参数
            output_args += self.opt_args

            if self.suffix == 'mp4':
                # 如果后缀是mp4，则添加特定的参数
                output_args += ['-bsf:a', 'aac_adtstoasc', '-f', 'mp4']
            elif self.suffix == 'ts':
                # 如果后缀是ts，则添加特定的参数
                output_args += ['-f', 'mpegts']
            elif self.suffix == 'mkv':
                # 如果后缀是mkv，则添加特定的参数
                output_args += ['-f', 'matroska']
            else:
                # 其他后缀，则直接添加后缀作为参数
                output_args += ['-f', self.suffix]

            # 构造ffmpeg命令参数列表
            args = ['ffmpeg', '-y', *input_args, *output_args, '-c', 'copy',
                    f'{fmt_file_name}.{self.suffix}.part']
            with subprocess.Popen(args, stdin=subprocess.DEVNULL if not streamlink_proc else streamlink_proc.stdout,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
                # 以下为注释掉的数据库操作代码
                # with SessionLocal() as db:
                #     update_file_list(db, self.database_row_id, fmt_file_name)
                #     updatedFileList = True

                # 遍历ffmpeg命令的输出
                for line in iter(proc.stdout.readline, b''):  # b'\n'-separated lines
                    # 解码输出行并去除末尾的换行符
                    decode_line = line.rstrip().decode(errors='ignore')
                    # 打印输出行
                    print(decode_line)
                    # 记录日志
                    logger.debug(decode_line)

            # 检查ffmpeg命令的返回值
            if proc.returncode == 0:
                # 如果返回值为0，则执行文件重命名操作
                # 文件重命名
                self.download_file_rename(f'{fmt_file_name}.{self.suffix}.part', f'{fmt_file_name}.{self.suffix}')
                # 触发分段事件
                self.__download_segment_callback(f'{fmt_file_name}.{self.suffix}')
                return True
            else:
                return False

        # 以下是异常处理部分的代码
        # except:
        #     if updatedFileList:
        #         with SessionLocal() as db:
        #             delete_file_list(db, self.database_row_id, None)

        finally:
            try:
                # 尝试终止streamlink进程
                if streamlink_proc:
                    streamlink_proc.terminate()
                    streamlink_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 如果超时，则强制终止streamlink进程
                streamlink_proc.kill()
            except:
                # 捕获其他异常并记录日志
                logger.exception(f'terminate {self.fname} failed')

    def __download_segment_callback(self, file_name: str):
        """
        分段后触发返回含后缀的文件名
        """
        # 提取不含后缀的文件名
        exclude_ext_file_name = os.path.splitext(file_name)[0]
        # 构造弹幕文件名
        danmaku_file_name = os.path.splitext(file_name)[0] + '.xml'

        if self.danmaku:
            # 保存弹幕文件
            self.danmaku.save(danmaku_file_name)

        def x():
            # 定义函数x，该函数用于执行后续操作
            # 将文件名和直播标题存储到数据库
            with SessionLocal() as db:
                update_file_list(db, self.database_row_id, file_name)

            if self.segment_processor:
                try:
                    # 如果设置了非并行处理且存在上一个线程，则等待上一个线程结束
                    if not self.segment_processor_parallel and prev_thread:
                        prev_thread.join()

                    # 导入处理器模块
                    from biliup.common.tools import processor

                    # 获取文件绝对路径
                    data = os.path.abspath(file_name)

                    # 如果弹幕文件存在，则将弹幕文件绝对路径添加到数据中
                    if os.path.exists(danmaku_file_name):
                        data += f'\n{os.path.abspath(danmaku_file_name)}'

                    # 执行分段处理器
                    processor(self.segment_processor, data)

                except:
                    # 捕获异常并记录日志
                    logger.warning(f'执行后处理失败：{self.__class__.__name__} - {self.fname}', exc_info=True)

        # 创建守护线程，目标函数为x
        thread = threading.Thread(target=x, daemon=True, name=f"segment_processor_{exclude_ext_file_name}")

        # 获取上一个处理线程，如果不存在则为None
        prev_thread = self.segment_processor_thread[-1] if self.segment_processor_thread else None

        # 将新创建的线程添加到线程列表中
        self.segment_processor_thread.append(thread)

        # 启动线程
        thread.start()


    def download_success_callback(self):
        pass

    def run(self):
        try:
            # 检查流是否可用
            if not asyncio.run_coroutine_threadsafe(self.acheck_stream(), loop).result():
                return False

            # 使用数据库会话
            with SessionLocal() as db:
                # 更新房间标题
                update_room_title(db, self.database_row_id, self.room_title)

            # 初始化弹幕
            self.danmaku_init()

            # 如果存在弹幕
            if self.danmaku:
                # 启动弹幕
                self.danmaku.start()

            # 下载
            retval = self.download()

            return retval
        finally:
            # 如果存在弹幕
            if self.danmaku:
                # 停止弹幕
                self.danmaku.stop()
                # 清除弹幕对象
                self.danmaku = None


    def start(self):
        logger.info(f'开始下载: {self.__class__.__name__} - {self.fname}')
        # 开始时间
        start_time = time.localtime()
        # 结束时间
        end_time = None

        with SessionLocal() as db:
            self.database_row_id = add_stream_info(db, self.fname, self.url, start_time)  # 返回数据库中此行记录的 id
        ret = True
        while ret:
            # 下载结果
            try:
                ret = self.run()
            except Exception:
                logger.warning(f'下载失败: {self.__class__.__name__} - {self.fname}', exc_info=True)
            finally:
                self.close()

            # 下载模式跳过下播延迟检测
            if self.is_download:
                break

            # 最后一次下载完成时间
            end_time = time.localtime()

        self.download_cover(
            time.strftime(self.gen_download_filename().encode("unicode-escape").decode(), end_time if end_time else time.localtime()
                           ).encode().decode("unicode-escape"))
        # 更新数据库中封面存储路径
        with SessionLocal() as db:
            update_cover_path(db, self.database_row_id, self.live_cover_path)

        for thread in self.segment_processor_thread:
            if thread.is_alive():
                logger.info(f'等待分段后处理完成: {self.__class__.__name__} - {self.fname} - {thread.name}')
                thread.join()
        if (self.is_download and ret) or not self.is_download:
            self.download_success_callback()
        # self.segment_processor_thread
        logger.info(f'退出下载: {self.__class__.__name__} - {self.fname}')
        stream_info = {
            'name': self.fname,
            'url': self.url,
            'title': self.room_title,
            'date': start_time,
            'end_time': end_time if end_time else time.localtime(),
            'live_cover_path': self.live_cover_path,
            'is_download': self.is_download,
        }
        return stream_info

    def download_cover(self, fmtname):
        # 下载封面图片
        # 获取封面
        if self.use_live_cover and self.live_cover_url is not None:
            try:
                # 设置保存目录
                save_dir = f'cover/{self.__class__.__name__}/{self.fname}/'
                # 如果目录不存在，则创建目录
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir)

                # 解析封面图片的URL路径
                url_path = urlparse(self.live_cover_url).path
                # 初始化图片后缀
                suffix = None
                # 根据URL路径判断图片后缀
                if '.jpg' in url_path:
                    suffix = 'jpg'
                elif '.png' in url_path:
                    suffix = 'png'
                elif '.webp' in url_path:
                    suffix = 'webp'

                # 如果存在后缀
                if suffix:
                    # 拼接封面图片的保存路径
                    live_cover_path = f'{save_dir}{fmtname}.{suffix}'
                    # 如果封面图片已存在，则直接设置路径
                    if os.path.exists(live_cover_path):
                        self.live_cover_path = live_cover_path
                    else:
                        # 发送请求获取封面图片
                        response = requests.get(self.live_cover_url, headers=self.fake_headers, timeout=30)
                        # 保存封面图片到本地
                        with open(live_cover_path, 'wb') as f:
                            f.write(response.content)

                    # 如果封面是webp格式，则转换为jpg格式
                    if suffix == 'webp':
                        # 使用PIL库将webp格式转换为jpg格式
                        with Image.open(live_cover_path) as img:
                            img = img.convert('RGB')
                            img.save(f'{save_dir}{fmtname}.jpg', format='JPEG')
                        # 删除webp格式的封面图片
                        os.remove(live_cover_path)
                        # 更新封面图片的保存路径
                        live_cover_path = f'{save_dir}{fmtname}.jpg'

                    # 设置封面图片的保存路径
                    self.live_cover_path = live_cover_path
                    # 记录日志，封面下载成功
                    logger.info(
                        f'封面下载成功：{self.__class__.__name__} - {self.fname}：{os.path.abspath(self.live_cover_path)}')
                else:
                    # 记录日志，封面下载失败，因为格式不支持
                    logger.warning(
                        f'封面下载失败：{self.__class__.__name__} - {self.fname}：封面格式不支持：{self.live_cover_url}')
            except:
                # 记录异常日志，封面下载失败
                logger.exception(f'封面下载失败：{self.__class__.__name__} - {self.fname}')

    async def acheck_url_healthy(self, url):
        # 内部辅助函数，用于发送 GET 请求并处理响应
        async def __client_get(url, stream: bool = False):
            # 更新请求头
            client.headers.update(self.fake_headers)
            if stream:
                # 如果需要流式处理，则使用 stream 方法发送 GET 请求
                async with client.stream("GET", url, timeout=60, follow_redirects=False) as response:
                    pass
            else:
                # 否则，使用 get 方法发送 GET 请求
                response = await client.get(url)
            # 如果响应状态码不是 301 或 302，则抛出异常
            if response.status_code not in (301, 302):
                response.raise_for_status()
            # 返回响应对象
            return response

        try:
            # 如果 URL 中包含 '.m3u8'
            if '.m3u8' in url:
                # 发送 GET 请求获取 m3u8 文件内容
                r = await __client_get(url)
                import m3u8
                # 解析 m3u8 文件内容
                m3u8_obj = m3u8.loads(r.text)
                # 如果是多码率流，则取第一个播放列表的 URL
                if m3u8_obj.is_variant:
                    url = m3u8_obj.playlists[0].uri
                    logger.info(f'stream url: {url}')
                    # 再次发送 GET 请求获取实际播放的 URL
                    r = await __client_get(url)
            else: # 处理 Flv
                # 发送流式 GET 请求获取 Flv 文件内容
                r = await __client_get(url, stream=True)
                # 如果响应头中包含 'Location'，则获取重定向的 URL
                if r.headers.get('Location'):
                    url = r.headers['Location']
                    logger.info(f'stream url: {url}')
                    # 再次发送流式 GET 请求获取重定向后的 Flv 文件内容
                    r = await __client_get(url, stream=True)
            # 如果响应状态码为 200，则返回 URL
            if r.status_code == 200:
                return url
        # 如果发生 HTTP 状态码错误
        except HTTPStatusError as e:
            logger.error(f'url {url}: status_code-{e.response.status_code}')
        # 如果发生其他异常
        except:
            logger.exception(f'url {url}: ')
        # 返回 None
        return None

    def gen_download_filename(self, is_fmt=False):
        # 判断是否存在自定义录播命名设置
        if self.filename_prefix:
            # 使用自定义的录播命名前缀格式化生成文件名，并进行编码转换
            filename = (self.filename_prefix.format(streamer=self.fname, title=self.room_title).encode(
                'unicode-escape').decode()).encode().decode("unicode-escape")
        else:
            # 如果没有自定义命名前缀，则使用默认命名规则生成文件名
            filename = f'{self.fname}%Y-%m-%dT%H_%M_%S'
        # 获取有效的文件名
        filename = get_valid_filename(filename)

        if is_fmt:
            # 获取当前时间戳
            file_time = time.time()
            while True:
                # 根据文件名格式和当前时间生成格式化文件名，并进行编码转换
                fmt_file_name = time.strftime(filename.encode("unicode-escape").decode(),
                                              time.localtime(file_time)).encode().decode("unicode-escape")
                # 如果格式化后的文件名对应的文件已存在
                if os.path.exists(f"{fmt_file_name}.{self.suffix}"):
                    # 时间戳加1，继续循环
                    file_time += 1
                else:
                    # 返回格式化后的文件名
                    return fmt_file_name
        else:
            # 返回文件名
            return filename


    @staticmethod
    def download_file_rename(old_file_name, file_name):
        try:
            # 尝试将文件从old_file_name重命名为file_name
            os.rename(old_file_name, file_name)
            # 记录日志，表示重命名成功
            logger.info(f'更名 {old_file_name} 为 {file_name}')
        except:
            # 捕获异常，记录日志表示重命名失败，并输出异常信息
            logger.error(f'更名 {old_file_name} 为 {file_name} 失败', exc_info=True)

    def danmaku_init(self):
        pass

    def close(self):
        pass


def stream_gears_download(url, headers, file_name, segment_time=None, file_size=None,
                          file_name_callback: Callable[[str], None] = None):
    class Segment:
        pass

    # 创建一个Segment类的实例
    segment = Segment()

    # 如果传入了segment_time参数
    if segment_time:
        # 将segment_time按冒号分割成列表
        seg_time = segment_time.split(':')
        # 计算总秒数并赋值给segment的time属性
        # print(int(seg_time[0]) * 60 * 60 + int(seg_time[1]) * 60 + int(seg_time[2]))
        segment.time = int(seg_time[0]) * 60 * 60 + int(seg_time[1]) * 60 + int(seg_time[2])

    # 如果传入了file_size参数
    if file_size:
        # 将file_size赋值给segment的size属性
        segment.size = file_size

    # 如果file_size和segment_time都为None
    if file_size is None and segment_time is None:
        # 将segment的size属性设置为8GB
        segment.size = 8 * 1024 * 1024 * 1024

    # 如果传入了file_name_callback参数
    # FIXME: 下载时如出现403，这里不会回到上层方法获取新链接
    if file_name_callback:
        # 调用stream_gears.download_with_callback方法，传入url、headers、file_name、segment和file_name_callback参数
        stream_gears.download_with_callback(
            url,
            headers,
            file_name,
            segment,
            file_name_callback
        )
    else:
        # 调用stream_gears.download方法，传入url、headers、file_name和segment参数
        stream_gears.download(
            url,
            headers,
            file_name,
            segment,
        )



def get_valid_filename(name):
    """
    Return the given string converted to a string that can be used for a clean
    filename. Remove leading and trailing spaces; convert other spaces to
    underscores; and remove anything that is not an alphanumeric, dash,
    underscore, or dot.
    # >>> get_valid_filename("john's portrait in 2004.jpg")
    >>> get_valid_filename("{self.fname}%Y-%m-%dT%H_%M_%S")
    '{self.fname}%Y-%m-%dT%H_%M_%S'
    """
    # s = str(name).strip().replace(" ", "_") #因为有些人会在主播名中间加入空格，为了避免和录播完毕自动改名冲突，所以注释掉
    # 使用正则表达式替换字符串中的非字母、数字、下划线、点、百分号、大括号、方括号、中文括号、中文引号、圆括号、点号、度号和空格等字符为空字符串
    s = re.sub(r"(?u)[^-\w.%{}\[\]【】「」（）・°\s]", "", str(name))

    # 如果替换后的字符串为空字符串、点号或两个点号，则抛出运行时错误
    if s in {"", ".", ".."}:
        raise RuntimeError("Could not derive file name from '%s'" % name)

    # 返回替换后的字符串
    return s



class BatchCheck(ABC):
    # 定义一个抽象静态方法，用于批量检查
    @staticmethod
    @abstractmethod
    # 定义一个异步生成器函数，用于返回检查结果的异步生成器
    async def abatch_check(check_urls: List[str]) -> AsyncGenerator[str, None]:

        """
        批量检测直播或下载状态
        返回的是url_list
        """
