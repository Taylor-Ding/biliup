import json
import logging
import os
import shutil
import subprocess
import time
from functools import reduce
from pathlib import Path
from typing import List

from biliup.config import config
from .app import event_manager, context
from .common.tools import NamedLock, processor
from .database.db import get_stream_info_by_filename, SessionLocal
from .downloader import biliup_download
from .engine.event import Event
from .engine.upload import UploadBase
from .uploader import upload, fmt_title_and_desc

PRE_DOWNLOAD = 'pre_download'
DOWNLOAD = 'download'
DOWNLOADED = 'downloaded'
UPLOAD = 'upload'
UPLOADED = 'uploaded'
logger = logging.getLogger('biliup')


# @event_manager.register(CHECK, block='Asynchronous3')


@event_manager.register(PRE_DOWNLOAD, block='Asynchronous1')
def pre_processor(name, url):
    # 检查URL状态，如果已经存在下载任务则跳过
    if context['PluginInfo'].url_status[url] == 1:
        logger.debug(f'{name} 正在下载中，跳过下载')
        return
    # 打印开始下载的消息
    logger.info(f'{name} - {url} 开播了准备下载')
    # 获取预处理器
    preprocessor = config['streamers'].get(name, {}).get('preprocessor')
    if preprocessor:
        # 调用预处理器
        processor(preprocessor, json.dumps({
            "name": name,
            "url": url,
            "start_time": int(time.time())
        }, ensure_ascii=False))
    # 发送 DOWNLOAD 事件，开始下载
    yield Event(DOWNLOAD, (name, url))


@event_manager.register(DOWNLOAD, block='Asynchronous1')
def process(name, url):
    url_status = context['PluginInfo'].url_status
    # 下载开始
    try:
        # 设置URL状态为正在下载
        url_status[url] = 1
        # 调用biliup_download函数进行下载
        stream_info = biliup_download(name, url, config['streamers'][name].copy())
        # 发送 DOWNLOADED 事件，下载完成
        yield Event(DOWNLOADED, (stream_info,))
    except Exception as e:
        # 捕获异常并记录日志
        logger.exception(f"下载错误: {name} - {e}")
    finally:
        # 下载结束，设置URL状态为未下载
        url_status[url] = 0


@event_manager.register(DOWNLOADED, block='Asynchronous1')
def processed(stream_info):
    name = stream_info['name']
    url = stream_info['url']
    # 下载后处理 上传前处理
    downloaded_processor = config['streamers'].get(name, {}).get('downloaded_processor')
    if downloaded_processor:
        default_date = time.localtime()
        file_list = UploadBase.file_list(name)
        # 调用下载后处理器
        processor(downloaded_processor, json.dumps({
            "name": name,
            "url": url,
            "room_title": stream_info.get('title', name),
            "start_time": int(time.mktime(stream_info.get('date', default_date))),
            "end_time": int(time.mktime(stream_info.get('end_time', default_date))),
            "file_list": [file.video for file in file_list]
        }, ensure_ascii=False))
        # 后处理完成后重新扫描文件列表
        # 发送 UPLOAD 事件，准备上传
    yield Event(UPLOAD, (stream_info,))


@event_manager.register(UPLOAD, block='Asynchronous2')
def process_upload(stream_info):
    url = stream_info['url']
    name = stream_info['name']
    url_upload_count = context['url_upload_count']
    # 使用 NamedLock 保证对同一URL的上传操作是原子性的
    # 永远不可能有两个同url的下载线程
    # 可能对同一个url同时发送两次上传事件
    with NamedLock(f"upload_count_{url}"):
        # 检查URL是否已经存在上传任务
        if context['url_upload_count'][url] > 0:
            return logger.debug(f'{url} 正在上传中，跳过')
        # 增加URL的上传计数
        context['url_upload_count'][url] += 1
    # 上传开始
    try:
        # 获取上传文件列表
        file_list = UploadBase.file_list(name)
        # 获取文件数量
        file_count = len(file_list)
        # 如果文件数量小于等于0，则无需上传
        if file_count <= 0:
            logger.debug("无需上传")
            return

        # 上传延迟检测
        # 获取URL状态
        url_status = context['PluginInfo'].url_status
        # 获取延迟时间
        delay = int(config.get('delay', 0))
        # 如果存在延迟时间
        if delay:
            # 打印日志，显示延迟上传信息
            logger.info(f'{name} -> {url} {delay}s 后检测是否上传')
            # 等待延迟时间
            time.sleep(delay)
            # 如果URL状态为下载中
            if url_status[url] == 1:
                # 上传延迟检测，启用的话会在一段时间后检测是否存在下载任务，若存在则跳过本次上传
                # 打印日志，显示存在下载任务，跳过本次上传
                return logger.info(f'{name} -> {url} 存在下载任务, 跳过本次上传')

        # 如果stream_info中没有标题或者标题为空
        if ("title" not in stream_info) or (not stream_info["title"]):
            # 说明下载信息已丢失，则尝试从数据库获取
            # 使用SessionLocal()创建数据库会话
            with SessionLocal() as db:
                i = 0
                # 循环遍历文件列表
                # 注意：按创建时间排序可能导致首个结果无法获取到数据
                # 上传延迟检测，启用的话会在一段时间后检测是否存在下载任务，若存在则跳过本次上传
                while i < file_count:
                    # 通过文件名从数据库中获取流信息
                    data = get_stream_info_by_filename(db, file_list[i].video)
                    # 如果获取到流信息
                    if data:
                        break
                    # 遍历下一个文件
                    i += 1
            # 格式化标题和描述，如果restart，data中会缺失name项
            data, _ = fmt_title_and_desc({**data, "name": name})
            # 更新stream_info中的信息
            stream_info.update(data)

        # 调用upload函数进行上传，返回上传的文件列表
        filelist = upload(stream_info)
        # 如果上传成功，即filelist不为空
        if filelist:
            # 调用uploaded函数进行上传后的处理
            uploaded(name, stream_info.get('live_cover_path'), filelist)
    # 捕获异常
    except Exception:
        # 打印上传错误日志
        logger.exception(f"上传错误: {name}")
    # 无论是否发生异常，都执行finally块中的代码
    finally:
        # 上传结束
        # 如果存在多个同URL的上传线程，使用NamedLock保证计数正确
        # 上传结束，保证计数正确
        with NamedLock(f'upload_count_{url}'):
            url_upload_count[url] -= 1

def uploaded(name, live_cover_path, data: List):
    # 获取上传后的处理函数
    # data = file_list
    post_processor = config['streamers'].get(name, {}).get("postprocessor", None)
    if post_processor is None:
        # 如果未定义处理函数，则执行以下操作
        # 删除封面
        if live_cover_path is not None:
            UploadBase.remove_file(live_cover_path)
        return UploadBase.remove_filelist(data)

    # 初始化文件列表
    file_list = []
    for i in data:
        file_list.append(i.video)
        if i.danmaku is not None:
            file_list.append(i.danmaku)

    # 遍历处理函数列表
    for post_processor in post_processor:
        if post_processor == 'rm':
            # 如果处理函数为'rm'，则执行以下操作
            # 删除封面
            if live_cover_path is not None:
                UploadBase.remove_file(live_cover_path)
            UploadBase.remove_filelist(data)
            continue
        if post_processor.get('mv'):
            # 如果处理函数包含'mv'参数，则执行文件移动操作
            for file in file_list:
                path = Path(file)
                dest = Path(post_processor['mv'])
                if not dest.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(path, dest / path.name)
                except Exception as e:
                    logger.exception(e)
                    continue
                logger.info(f"move to {(dest / path.name).absolute()}")
        if post_processor.get('run'):
            # 如果处理函数包含'run'参数，则执行外部命令
            try:
                process_output = subprocess.check_output(
                    post_processor['run'], shell=True,
                    input=reduce(lambda x, y: x + str(Path(y).absolute()) + '\n', file_list, ''),
                    stderr=subprocess.STDOUT, text=True)
                logger.info(process_output.rstrip())
            except subprocess.CalledProcessError as e:
                logger.exception(e.output)
                continue


