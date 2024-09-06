import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from sqlalchemy import create_engine, ForeignKey, JSON, TEXT, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase

logger = logging.getLogger('biliup')


# FIXME: 不应该在 stop 和 --version 时创建文件夹
def get_path(*other):
    """获取数据文件绝对路径"""
    dir_path = Path.cwd().joinpath("data")
    # 若目录不存在则创建
    if not dir_path.is_dir():
        dir_path.mkdir(parents=True)
    return str(dir_path.joinpath(*other))


DB_PATH = get_path('data.sqlite3')
DB_URL = f"sqlite:///{DB_PATH}"  # 数据库 URL, 使用默认 DBAPI

engine = create_engine(
    DB_URL, connect_args={"check_same_thread": False}
    # echo=True,  # 显示执行的 SQL 记录, 仅调试用, 发布前请注释
)

convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Base = declarative_base()
class BaseModel(DeclarativeBase):
    """ 数据库表模型基类 """
    def as_dict(self):
        """ 将实例转为字典类型 """
        # 深复制避免对原数据影响
        temp = copy.deepcopy(self.__dict__)  # 深复制避免对原数据影响
        result = dict()
        # 遍历删除不能被 json 序列化的键值对
        for key, value in temp.items():  # 遍历删除不能被 json 序列化的键值对
            # 特殊处理，保留 datetime
            if isinstance(value, datetime):  # 特殊处理，保留 datetime
                result[key] = value
                continue
            try:
                # 尝试将值转为 json 格式
                json.dumps(value)
                result[key] = value
            except TypeError:
                # 若值不能被 json 序列化，则跳过
                continue
        return result


    @classmethod
    def filter_parameters(cls, data: Dict[str, Any]):
        """ 过滤不需要的参数 """
        # 创建一个空字典用于存储过滤后的参数
        result = dict()
        # 遍历传入的参数字典
        for k, v in data.items():
            # 如果参数键存在于类的__table__的列中，或者参数键为"id"，则将该参数加入到结果字典中
            if (k in cls.__table__.c.keys()) or (k == "id"):
                result[k] = v
        # 返回过滤后的参数字典
        return result


# 定义命名惯例，避免生成自动迁移脚本时约束命名报错
BaseModel.metadata = MetaData(naming_convention=convention)  # 定义命名惯例，避免生成自动迁移脚本时约束命名报错
# BaseModel.metadata.reflect(bind=engine)  # 绑定反射会导致表重复定义


class StreamerInfo(BaseModel):
    """下载信息"""
    __tablename__ = "streamerinfo"

    # 自增主键
    id: Mapped[int] = mapped_column(primary_key=True)  # 自增主键
    # streamer 名称
    name: Mapped[str] = mapped_column(nullable=False)  # streamer 名称
    # 录制的 url
    url: Mapped[str] = mapped_column(nullable=False)  # 录制的 url
    # 直播标题
    title: Mapped[str] = mapped_column(nullable=False)  # 直播标题
    # 开播时间
    date: Mapped[datetime] = mapped_column(nullable=False)  # 开播时间
    # 封面存储路径
    live_cover_path: Mapped[str] = mapped_column(nullable=False)  # 封面存储路径
    # 关联的 FileList 列表
    filelist: Mapped[List["FileList"]] = relationship(back_populates="streamerinfo")


class FileList(BaseModel):
    """存储文件名列表, 通过外键和 StreamerInfo 表关联"""
    __tablename__ = "filelist"

    # 自增主键
    id: Mapped[int] = mapped_column(primary_key=True)  # 自增主键
    # 文件名
    file: Mapped[str] = mapped_column(nullable=False)  # 文件名
    # 外键, 对应 StreamerInfo 中的下载信息, 且启用级联删除
    streamer_info_id = mapped_column(ForeignKey("streamerinfo.id", ondelete="CASCADE"), nullable=False)
    # 与 StreamerInfo 表建立关系，back_populates 表示 StreamerInfo 类中也有一个名为 filelist 的属性与之对应
    streamerinfo: Mapped[StreamerInfo] = relationship(back_populates="filelist")


class Configuration(BaseModel):
    """暂时将配置文件整体存入，后续可拆表拆字段"""
    __tablename__ = "configuration"

    # 自增主键
    id: Mapped[int] = mapped_column(primary_key=True)  # 自增主键
    # 全局配置键
    key: Mapped[str] = mapped_column(nullable=False)  # 全局配置键
    # 全局配置值
    value = mapped_column(TEXT(), nullable=False)  # 全局配置值


class UploadStreamers(BaseModel):
    """投稿模板"""
    __tablename__ = "uploadstreamers"

    # 自增主键
    id: Mapped[int] = mapped_column(primary_key=True)  # 自增主键
    # 模板名称
    template_name: Mapped[str] = mapped_column(nullable=False)  # 模板名称
    # 自定义标题的时间格式, {title}代表当场直播间标题 {streamer}代表在本config里面设置的主播名称 {url}代表设置的该主播的第一条直播间链接
    title: Mapped[str] = mapped_column(
        nullable=True)  # 自定义标题的时间格式, {title}代表当场直播间标题 {streamer}代表在本config里面设置的主播名称 {url}代表设置的该主播的第一条直播间链接
    # 投稿分区码,171为电子竞技分区
    tid: Mapped[int] = mapped_column(nullable=True)  # 投稿分区码,171为电子竞技分区
    # 1为自制 2转载
    copyright: Mapped[int] = mapped_column(nullable=True)  # 1为自制 2转载
    # 转载来源
    copyright_source: Mapped[str] = mapped_column(nullable=True)  # 转载来源
    # 封面路径
    cover_path: Mapped[str] = mapped_column(nullable=True)  # 封面路径

    # 支持strftime, {title}, {streamer}, {url}占位符。
    # 视频简介
    description = mapped_column(TEXT(), nullable=True)  # 视频简介
    # 粉丝动态
    dynamic: Mapped[str] = mapped_column(nullable=True)  # 粉丝动态
    # 设置延时发布时间，距离提交大于2小时，格式为时间戳
    dtime: Mapped[int] = mapped_column(nullable=True)  # 设置延时发布时间，距离提交大于2小时，格式为时间戳
    # 是否开启杜比音效, 1为开启
    dolby: Mapped[int] = mapped_column(nullable=True)  # 是否开启杜比音效, 1为开启
    # 是否开启Hi-Res, 1为开启
    hires: Mapped[int] = mapped_column(nullable=True)  # 是否开启Hi-Res, 1为开启
    # 是否开启充电面板, 1为开启
    open_elec: Mapped[int] = mapped_column(nullable=True)  # 是否开启充电面板, 1为开启
    # 自制声明, 1为未经允许禁止转载
    no_reprint: Mapped[int] = mapped_column(nullable=True)  # 自制声明, 1为未经允许禁止转载
    # 覆盖全局默认上传插件，Noop为不上传，但会执行后处理
    uploader: Mapped[str] = mapped_column(nullable=True)  # 覆盖全局默认上传插件，Noop为不上传，但会执行后处理
    # 使用指定的账号上传
    user_cookie: Mapped[str] = mapped_column(nullable=True)  # 使用指定的账号上传
    # 标签
    tags = mapped_column(JSON(), nullable=False)  # JSONField()  # 标签
    # 简介@模板
    credits = mapped_column(JSON(), nullable=True)  # JSONField(null=True)  # 简介@模板
    # 精选评论
    up_selection_reply: Mapped[int] = mapped_column(nullable=True)  # 精选评论
    # 关闭评论
    up_close_reply: Mapped[int] = mapped_column(nullable=True)  # 关闭评论
    # 精选评论
    up_close_danmu: Mapped[int] = mapped_column(nullable=True)  # 精选评论

    # 与LiveStreamers表建立关系
    livestreamers: Mapped[List["LiveStreamers"]] = relationship(back_populates="uploadstreamers")


class LiveStreamers(BaseModel):
    """每个直播间的配置"""
    __tablename__ = "livestreamers"

    # 自增主键
    id: Mapped[int] = mapped_column(primary_key=True)  # 自增主键
    # 直播间地址
    url: Mapped[str] = mapped_column(nullable=False, unique=True)  # 直播间地址
    # 对应配置文件中 {streamer} 变量
    remark: Mapped[str] = mapped_column(nullable=False)  # 对应配置文件中 {streamer} 变量
    # filename_prefix 支持模板
    filename_prefix: Mapped[str] = mapped_column(nullable=True)  # filename_prefix 支持模板
    # 外键, 对应 UploadStreamers, 且启用级联删除
    upload_streamers_id = mapped_column(ForeignKey("uploadstreamers.id", ondelete="CASCADE"), nullable=True)
    # 与 UploadStreamers 表建立关系，back_populates 表示 UploadStreamers 类中也有一个名为 livestreamers 的属性与之对应
    uploadstreamers: Mapped[UploadStreamers] = relationship(back_populates="livestreamers")
    # 视频格式
    format: Mapped[str] = mapped_column(nullable=True)  # 视频格式
    # 开始下载直播时触发
    preprocessor = mapped_column(JSON(), nullable=True)  # 开始下载直播时触发
    # 分段时触发
    segment_processor = mapped_column(JSON(), nullable=True)  # 分段时触发
    # 准备上传直播时触发
    downloaded_processor = mapped_column(JSON(), nullable=True)  # 准备上传直播时触发
    # 上传完成后触发
    postprocessor = mapped_column(JSON(), nullable=True)  # 上传完成后触发
    # ffmpeg参数
    opt_args = mapped_column(JSON(), nullable=True)  # ffmpeg参数
