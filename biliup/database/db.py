import contextvars
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import logging

logger = logging.getLogger('biliup')

from sqlalchemy import select, desc, delete
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from alembic import command, config

from .models import (
    # 数据库文件路径
    DB_PATH,
    # 数据库引擎
    engine,
    # 基础模型
    BaseModel,
    # 流媒体信息模型
    StreamerInfo,
    # 文件列表模型
    FileList,
)

# 创建一个sessionmaker对象，绑定到数据库引擎engine，并设置autocommit为False
SessionLocal = sessionmaker(bind=engine, autocommit=False)

# 使用 Context ID 区分会话
# Session = scoped_session(session_factory, scopefunc=lambda: id(contextvars.copy_context()))


def struct_time_to_datetime(date: time.struct_time):
    # 将 struct_time 对象转换为时间戳
    # 然后将时间戳转换为 datetime 对象
    return datetime.fromtimestamp(time.mktime(date))


def datetime_to_struct_time(date: datetime):
    # 将 datetime 对象转换为时间戳
    # 然后将时间戳转换为 struct_time 对象
    return time.localtime(date.timestamp())



def init(no_http, from_config):
    """初始化数据库"""
    # 判断是否为首次运行
    first_run = not Path.cwd().joinpath("data/data.sqlite3").exists()

    # 如果no_http为True，且不是首次运行，且从配置文件中加载配置
    if no_http and not first_run and from_config:
        # 备份数据库文件
        new_name = f'{DB_PATH}.backup'
        if os.path.exists(new_name):
            # 如果备份文件已存在，则删除备份文件
            os.remove(new_name)
        # 将当前数据库文件重命名为备份文件
        os.rename(DB_PATH, new_name)
        # 输出备份文件路径
        print(f"旧数据库已备份为: {new_name}")  # 在logger加载配置之前执行，只能使用print

    # 创建所有表
    BaseModel.metadata.create_all(engine)  # 创建所有表

    # 迁移数据库
    migrate_via_alembic()

    # 返回首次运行或no_http为True的结果
    return first_run or no_http



def get_stream_info(db: Session, name: str) -> dict:
    """根据 streamer 获取下载信息, 若不存在则返回空字典"""
    # 在数据库中查询名为 name 的 StreamerInfo 记录，并按照 id 降序排序，取第一条记录
    res = db.execute(
        select(StreamerInfo).
        filter_by(name=name).
        order_by(desc(StreamerInfo.id))
    ).first()

    # 如果查询结果不为空
    if res:
        # 将查询结果转换为字典形式
        res = res._asdict()

        # 将日期字段从 datetime 对象转换为 struct_time 对象
        res["date"] = datetime_to_struct_time(res["date"])

        # 返回查询结果字典
        return res

    # 如果查询结果为空，返回空字典
    return {}



def get_stream_info_by_filename(db: Session, filename: str) -> dict:
    """通过文件名获取下载信息, 若不存在则返回空字典"""
    try:
        # 使用SQLAlchemy的select和where方法构造查询语句，通过文件名查找FileList记录
        # stream_info = FileList.get(FileList.file == filename).streamer_info
        stmt = select(FileList).where(FileList.file == filename)
        # 执行查询语句，并获取单个结果中的streamerinfo字段值
        stream_info = db.execute(stmt).scalar_one().streamerinfo
        # 将查询结果转换为字典形式
        stream_info_dict = stream_info.as_dict()
    except Exception as e:
        # 如果发生异常，记录日志并返回空字典
        logger.debug(f"{e}")
        return {}
    # 使用字典推导式清除字典中的空元素
    stream_info_dict = {key: value for key, value in stream_info_dict.items() if value}  # 清除字典中的空元素
    # 将开播时间字段的值从datetime类型转换为struct_time类型
    stream_info_dict["date"] = datetime_to_struct_time(stream_info_dict["date"])  # 将开播时间转回 struct_time 类型
    return stream_info_dict



def add_stream_info(db: Session, name: str, url: str, date: time.struct_time) -> int:
    """添加下载信息, 返回所添加行的 id """
    # 创建一个 StreamerInfo 对象，并设置其属性值
    streamerinfo = StreamerInfo(
        name=name,  # 设置 name 属性
        url=url,    # 设置 url 属性
        # 将 struct_time 对象转换为 datetime 对象，并设置给 date 属性
        date=struct_time_to_datetime(date),
        title="",   # 设置 title 属性为空字符串
        live_cover_path="",  # 设置 live_cover_path 属性为空字符串
    )
    # 将 StreamerInfo 对象添加到数据库会话中
    db.add(streamerinfo)
    # 提交数据库会话，使更改生效
    db.commit()
    # 返回所添加行的 id
    return streamerinfo.id



def delete_stream_info(db: Session, name: str) -> int:
    """根据 streamer 删除下载信息, 返回删除的行数, 若不存在则返回 0 """
    # 执行删除操作，根据 streamer 的名称删除对应的下载信息
    result = db.execute(
        delete(StreamerInfo).where(StreamerInfo.name == name))
    # 提交数据库事务
    db.commit()
    # # 刷新数据库中的数据（该行代码被注释掉了）
    # db.refresh(result)
    # 返回删除的行数
    return result.rowcount()


def delete_stream_info_by_date(db: Session, name: str, date: time.struct_time) -> int:
    """根据 streamer 和开播时间删除下载信息, 返回删除的行数, 若不存在则返回 0 """
    # 将开播时间转换为 datetime 对象
    start_datetime = struct_time_to_datetime(date)
    # 构建删除语句，根据 streamer 的名称和开播时间范围删除对应的下载信息
    stmt = delete(StreamerInfo).where(
        (StreamerInfo.name == name),
        StreamerInfo.date.between(
            start_datetime - timedelta(minutes=1),
            start_datetime + timedelta(minutes=1)),
    )
    # 执行删除操作
    result = db.execute(stmt)
    # 提交数据库事务
    db.commit()
    # 返回删除的行数
    return result.rowcount()



def update_cover_path(db: Session, database_row_id: int, live_cover_path: str):
    """更新封面存储路径"""
    # 如果传入的封面路径为空，则将其设置为空字符串
    if not live_cover_path:
        live_cover_path = ""

    # 根据传入的数据库行ID查询StreamerInfo记录
    streamerinfo = db.scalar(select(StreamerInfo).where(StreamerInfo.id == database_row_id))

    # 更新StreamerInfo记录的封面路径字段为传入的封面路径
    streamerinfo.live_cover_path = live_cover_path

    # 提交数据库事务，将更新保存至数据库
    db.commit()



def update_room_title(db: Session, database_row_id: int, title: str):
    """更新直播标题"""
    # 如果传入的标题为空，则将标题设置为空字符串
    if not title:
        title = ""

    # 根据数据库行ID查询StreamerInfo对象
    streamerinfo = db.get(StreamerInfo, database_row_id)

    # 更新StreamerInfo对象的标题字段
    streamerinfo.title = title

    # 提交数据库事务
    db.commit()



def update_file_list(db: Session, database_row_id: int, file_name: str) -> int:
    """向视频文件列表中添加文件名"""
    # 根据数据库行ID获取StreamerInfo对象
    streamer_info = db.get(StreamerInfo, database_row_id)
    # 创建一个FileList对象，并设置文件名和StreamerInfo对象的ID
    file_list = FileList(file=file_name, streamer_info_id=streamer_info.id)
    # 将FileList对象添加到数据库中
    db.add(file_list)
    # 提交数据库事务
    db.commit()
    # 返回新添加的FileList对象的ID
    return file_list.id


# def delete_file_list(db: Session, database_row_id: int, file_name: str) -> int:
#     """从视频文件列表中删除指定的文件名，返回删除的行数，若不存在则返回 0"""
#     # 查询数据库以获取对应的streamer_info
#     streamer_info = db.get(StreamerInfo, database_row_id)
#     if not streamer_info:
#         return 0
#     stmt = delete(FileList).where(
#         (FileList.file == file_name),
#         (FileList.streamer_info_id == streamer_info.id)
#     )
#     result = db.execute(stmt)
#     db.commit()
#     return result.rowcount


def get_file_list(db: Session, database_row_id: int) -> List[str]:
    """获取视频文件列表"""
    # 从数据库中获取指定ID的StreamerInfo对象
    streamer_info = db.get(StreamerInfo, database_row_id)
    # 获取StreamerInfo对象的filelist属性，即文件列表
    file_list = streamer_info.filelist
    # 遍历文件列表，提取每个文件的file属性，构建视频文件列表并返回
    return [file.file for file in file_list]



def migrate_via_alembic():
    """ 自动迁移，通过 alembic 实现 """
    def process_revision_directives(context, revision, directives):
        """ 如果无改变，不生成迁移脚本 """
        script = directives[0]
        if script.upgrade_ops.is_empty():
            # 如果升级操作为空，则清空指令列表
            directives[:] = []

    # 初始化alembic配置对象
    alembic_cfg = config.Config()

    # 获取脚本路径
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration")
    # 获取版本脚本路径
    versions_scripts_path = os.path.join(script_path, 'versions')

    # 如果版本脚本路径不存在，则创建
    if not os.path.exists(versions_scripts_path):
        os.makedirs(versions_scripts_path, 0o700)

    # 设置脚本位置
    alembic_cfg.set_main_option('script_location', script_path)

    # 将当前标记为最新版
    command.stamp(alembic_cfg, 'head', purge=True)  # 将当前标记为最新版

    # 自动生成迁移脚本
    scripts = command.revision(  # 自动生成迁移脚本
        alembic_cfg,
        autogenerate=True,
        process_revision_directives=process_revision_directives
    )

    # 如果没有生成迁移脚本，则输出提示信息并返回
    if not scripts:
        print("数据库已是最新版本")
        return

    # 执行迁移操作
    command.upgrade(alembic_cfg, 'head')

    # 输出迁移完成信息
    print("检测到旧版数据库，已完成自动迁移")

def backup(db: Session):
    """备份数据库"""
    pass

