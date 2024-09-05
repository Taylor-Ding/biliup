import json
import pathlib
import shutil
import os
from collections import UserDict
from sqlalchemy import select


try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


class Config:
    """
    配置类，用于处理和存储配置信息。
    """

    def __init__(self):
        """
        初始化配置类，加载默认配置。
        """
        self.load('config.yaml')

    def update_streamers_info(self, ls):
        """
        更新流媒体信息到内部存储。

        :param ls: LiveStreamers对象，包含流媒体信息。
        """
        # 将ls对象的属性添加到self['streamers'][ls.remark]字典中，排除特定字段。
        self['streamers'][ls.remark] = {
            k: v for k, v in ls.as_dict().items() if v and (k not in ['upload_streamers_id', 'id', 'remark'])}
        # 移除upload_streamers字段
        # self['streamers'][ls.remark].pop('upload_streamers')
        # 如果ls的upload_streamers_id存在，则将uploadstreamers对象的属性添加到流媒体信息中，排除特定字段。
        if ls.upload_streamers_id:
            self['streamers'][ls.remark].update({
                k: v for k, v in ls.uploadstreamers.as_dict().items() if v and k not in ['id', 'template_name']})
            # 如果uploader字段为空，则设置为默认值
            if self['streamers'][ls.remark].get('uploader') is None:
                self['streamers'][ls.remark]['uploader'] = 'biliup-rs'
        # 保留tags字段
        # if self['streamers'][ls.remark].get('tags'):
        #     self['streamers'][ls.remark]['tags'] = self['streamers'][ls.remark]['tags']
        # 遍历UploadStreamers表，将配置数据保存到数据库
        # for us in UploadStreamers.select():
        #     config.data[con.key] = con.value

    def save_to_db(self, db):
        """
        将配置信息保存到数据库。

        :param db: 数据库对象。
        """
        from biliup.database.models import Configuration, LiveStreamers, UploadStreamers
        # 遍历streamers字典，创建UploadStreamers和LiveStreamers对象并添加到数据库。
        for k, v in self['streamers'].items():
            us = UploadStreamers(**UploadStreamers.filter_parameters(
                {"template_name": k, "tags": v.pop('tags', [k]), ** v}))
            db.add(us)
            db.flush()
            url = v.pop('url')
            urls = url if isinstance(url, list) else [url]  # 兼容 url 输入字符串和列表
            for url in urls:
                ls = LiveStreamers(**LiveStreamers.filter_parameters(
                    {"upload_streamers_id": us.id, "remark": k, "url": url, ** v}))
                db.add(ls)
        del self['streamers']
        # 将其他配置信息保存到数据库
        configuration = Configuration(key='config', value=json.dumps(self.data))
        db.add(configuration)
        db.commit()

    def load(self, file):
        """
        从文件中加载配置信息。

        :param file: 配置文件对象。
        """
        import yaml
        # 如果未提供文件，则尝试加载默认配置文件
        if file is None:
            if pathlib.Path('config.yaml').exists():
                file = open('config.yaml', 'rb')
            elif pathlib.Path('config.toml').exists():
                self.data['toml'] = True
                file = open('config.toml', "rb")
            else:
                raise FileNotFoundError('未找到配置文件，请先创建配置文件')
        with file as stream:
            # 根据文件类型，使用yaml或toml加载配置信息
            if file.name.endswith('.toml'):
                self.data = tomllib.load(stream)
            else:
                self.data = yaml.load(stream, Loader=yaml.FullLoader)

    def create_without_config_input(self, file):
        """
        在没有配置输入的情况下创建配置。

        :param file: 配置文件对象。
        """
        import yaml
        # 如果未提供文件，则尝试加载默认配置文件或创建新的配置文件
        if file is None:
            if pathlib.Path('config.toml').exists():
                file = open('config.toml', 'rb')
            elif pathlib.Path('config.yaml').exists():
                file = open('config.yaml', encoding='utf-8')
            else:
                try:
                    from importlib.resources import files
                except ImportError:
                    from importlib.resources import files
                shutil.copy(files("biliup.web").joinpath('public/config.toml'), '.')
                file = open('config.toml', 'rb')

        # 从文件中加载配置信息
        with file as stream:
            if file.name.endswith('.toml'):
                self.data = tomllib.load(stream)
                self.data['toml'] = True
            else:
                self.data = yaml.load(stream, Loader=yaml.FullLoader)

    def save(self):
        """
        保存配置信息到文件。
        """
        # 根据配置类型（yaml或toml），将更新后的配置信息保存到相应的配置文件中
        if self.data.get('toml'):
            import tomli_w
            with open('config.toml', 'rb') as stream:
                old_data = tomllib.load(stream)
                old_data["lines"] = self.data["lines"]
                old_data["threads"] = self.data["threads"]
                old_data["streamers"] = self.data["streamers"]
            with open('config.toml', 'wb') as stream:
                tomli_w.dump(old_data, stream)
        else:
            import yaml
            with open('config.yaml', 'w+', encoding='utf-8') as stream:
                old_data = yaml.load(stream, Loader=yaml.FullLoader)
                old_data["user"]["cookies"] = self.data["user"]["cookies"]
                old_data["user"]["access_token"] = self.data["user"]["access_token"]
                old_data["lines"] = self.data["lines"]
                old_data["threads"] = self.data["threads"]
                old_data["streamers"] = self.data["streamers"]
                yaml.dump(old_data, stream, default_flow_style=False, allow_unicode=True)

    def dump(self, file):
        """
        将配置信息转储到旧版配置文件。

        :param file: 配置文件路径。
        :return: 配置文件路径。
        """
        # 如果未提供文件名，默认为config.toml
        if not file:
            file = 'config.toml'
        # 如果配置文件已存在，则重命名为备份文件
        if os.path.exists(file):
            from datetime import datetime
            import logging
            logger = logging.getLogger('biliup')
            new_name = f'{file}.backup.{datetime.now().strftime("%Y%m%d%H%M%S")}'
            logger.info(f"{file} 文件已存在，已将原文件重命名为 {new_name}")
            os.rename(file, new_name)
        # 排除不需要转储的键
        exclude_keys = ['PluginInfo', 'upload_filename', 'url_upload_count']
        temp = {k: v for k, v in self.data.items() if k not in exclude_keys}
        # 根据文件类型，使用yaml或toml转储配置信息
        if self.data.get('yaml') or file.endswith(".yaml"):
            import yaml
            with open(file, 'w+', encoding='utf-8') as stream:
                yaml.dump(temp, stream, default_flow_style=False, allow_unicode=True)
        else:
            import tomli_w
            with open(file, 'wb') as stream:
                tomli_w.dump(temp, stream)
        return file


# 创建并初始化配置对象
config = Config()

