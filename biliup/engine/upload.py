import logging
import os
import pathlib
import shutil

from typing import NamedTuple, Optional, List

from sqlalchemy import desc

from biliup.common.tools import NamedLock, get_file_create_timestamp
from biliup.config import config
from biliup.database import models
from biliup.database.db import SessionLocal

logger = logging.getLogger('biliup')


class UploadBase:
    class FileInfo(NamedTuple):
        # 视频文件路径
        video: str
        # 弹幕文件路径，可为空
        danmaku: Optional[str]


    def __init__(self, principal, data, persistence_path=None, postprocessor=None):
        # 初始化函数
        # 设置 principal 成员变量
        self.principal = principal
        # 设置 persistence_path 成员变量
        self.persistence_path = persistence_path
        # 设置 data 成员变量，类型为字典
        self.data: dict = data
        # 设置 post_processor 成员变量
        self.post_processor = postprocessor


    @staticmethod
    def file_list(index) -> List[FileInfo]:
        from biliup.handler import event_manager
        media_extensions = ['.mp4', '.flv', '.3gp', '.webm', '.mkv', '.ts']

        # 初始化一个空列表，用于存放文件列表
        # 获取文件列表
        file_list = []
        # 初始化一个空列表，用于存放数据库中保存的文件名（不含后缀）
        # 数据库中保存的文件名, 不含后缀
        save = []

        # 使用数据库会话，查询StreamerInfo表中符合条件的记录
        with SessionLocal() as db:
            # 查询StreamerInfo表中，name字段等于index的记录，并按照id字段降序排列，取出第一条记录
            dbinfo = db.query(models.StreamerInfo).filter(models.StreamerInfo.name == index).order_by(
                desc(models.StreamerInfo.id)).first()

            # 如果查询结果不为空
            if dbinfo:
                # 遍历dbinfo的filelist属性中的每个文件对象
                for dbfile in dbinfo.filelist:
                    # 将文件名添加到save列表中
                    save.append(dbfile.file)

        # 遍历当前目录下的所有文件和文件夹
        for file_name in os.listdir('.'):
            # 如果文件名中包含index，或者文件名（去掉后缀）在save列表中，并且该文件确实存在
            # 可能有两层后缀.with_suffix('')去掉一层.stem取文件名
            if (index in file_name or pathlib.Path(file_name).with_suffix('').stem in save ) and os.path.isfile(file_name):
                # 将文件名添加到file_list列表中
                file_list.append(file_name)

        # 如果file_list列表为空，则返回空列表
        if len(file_list) == 0:
            return []

        # 按照文件的创建时间对file_list列表进行排序
        file_list = sorted(file_list, key=lambda x: get_file_create_timestamp(x))

        # 从event_manager的context中获取正在上传的文件列表
        # 正在上传的文件列表
        upload_filename: list = event_manager.context['upload_filename']

        results = []
        for index, file in enumerate(file_list):
            old_name = file
            if file.endswith('.part'):
                # 如果文件名以.part结尾，则去掉.part后缀
                file_list[index] = os.path.splitext(file)[0]
                file = os.path.splitext(file)[0]

            name, ext = os.path.splitext(file)

            # 过滤正在上传的文件
            # 过滤正在上传的
            if name in upload_filename:
                continue

            # 过滤不是视频文件的文件
            # 过滤不是视频的
            if ext not in media_extensions:
                continue

            if old_name != file:
                # 如果文件名发生了更改，则记录日志并执行重命名操作
                logger.info(f'{old_name} 已更名为 {file}')
                shutil.move(old_name, file)

            # 获取文件大小（单位：MB）
            file_size = os.path.getsize(file) / 1024 / 1024

            # 获取过滤阈值
            threshold = config.get('filtering_threshold', 0)

            # 如果文件大小小于等于阈值，则删除文件并记录日志
            if file_size <= threshold:
                os.remove(file)
                logger.info(f'过滤删除 - {file}')
                continue

            # 初始化视频文件和弹幕文件变量
            video = file
            danmaku = None

            # 如果存在对应的弹幕文件，则设置弹幕文件变量
            if f'{name}.xml' in file_list:
                danmaku = f'{name}.xml'

            # 创建FileInfo对象并添加到结果列表中
            result = UploadBase.FileInfo(video=video, danmaku=danmaku)
            results.append(result)


        # 过滤弹幕
        for file in file_list:
            name, ext = os.path.splitext(file)

            # 过滤正在上传的文件
            # 过滤正在上传的
            if name in upload_filename:
                continue

            # 如果是弹幕文件
            if ext == '.xml':
                have_video = False

                # 遍历结果列表，检查是否存在对应的视频文件
                for result in results:
                    if result.danmaku == file:
                        have_video = True
                        break

                # 如果没有找到对应的视频文件，则删除该弹幕文件
                if not have_video:
                    logger.info(f'无视频，过滤删除 - {file}')
                    UploadBase.remove_file(file)

        return results


    @staticmethod
    def remove_filelist(file_list: List[FileInfo]):
        # 遍历文件列表
        for f in file_list:
            # 删除视频文件
            UploadBase.remove_file(f.video)
            # 如果存在弹幕文件
            if f.danmaku is not None:
                # 删除弹幕文件
                UploadBase.remove_file(f.danmaku)

    @staticmethod
    def remove_file(file: str):
        try:
            # 尝试删除文件
            os.remove(file)
            # 记录删除成功的日志
            logger.info(f'删除 - {file}')
        except:
            # 如果删除失败，记录删除失败的日志
            logger.warning(f'删除失败 - {file}')


    def upload(self, file_list: List[FileInfo]) -> List[FileInfo]:
        # 抛出未实现错误，子类需要实现该方法
        raise NotImplementedError()

    def start(self):
        from biliup.handler import event_manager
        # 使用命名锁，确保一个name同时只有一个上传线程扫描文件列表
        # 保证一个name同时只有一个上传线程扫描文件列表
        lock = NamedLock(f'upload_file_list_{self.principal}')
        upload_filename_list = []
        try:
            # 获取命名锁
            lock.acquire()
            # 获取文件列表
            file_list = UploadBase.file_list(self.principal)

            if len(file_list) > 0:
                # 提取文件名列表
                upload_filename_list = [os.path.splitext(file.video)[0] for file in file_list]

                # 打印准备上传的标题信息
                logger.info('准备上传' + self.data["format_title"])
                # 使用命名锁，确保上传文件名的线程安全
                with NamedLock('upload_filename'):
                    # 将文件名列表添加到上传文件名列表中
                    event_manager.context['upload_filename'].extend(upload_filename_list)
                # 释放命名锁
                lock.release()
                # 调用upload方法上传文件，并返回结果
                file_list = self.upload(file_list)
                return file_list
        finally:
            # 使用命名锁，确保上传文件名列表的线程安全
            with NamedLock('upload_filename'):
                # 从上传文件名列表中移除当前上传的文件名列表
                event_manager.context['upload_filename'] = list(
                    set(event_manager.context['upload_filename']) - set(upload_filename_list))
            # 如果命名锁仍被锁定，则释放它
            if lock.locked():
                lock.release()

