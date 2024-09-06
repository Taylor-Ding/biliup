from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from biliup.database.models import BaseModel

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    from biliup.database.models import DB_URL
    # 配置上下文
    context.configure(
        # 数据库连接URL
        url=DB_URL,
        # 目标元数据
        target_metadata=target_metadata,
        # 使用字面绑定
        literal_binds=True,
        # 方言选项，使用命名参数风格
        dialect_opts={"paramstyle": "named"},
        # 以批处理模式渲染，处理 sqlite 约束变化
        render_as_batch=True,  # 使用批处理模式，以处理 sqlite 约束变化
    )

    # 开始事务
    with context.begin_transaction():
        # 运行迁移
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    from biliup.database.models import DB_URL
    # 创建数据库引擎，使用 NullPool 作为连接池
    connectable = create_engine(
        DB_URL, poolclass=pool.NullPool,
    )

    # 使用数据库引擎建立连接
    with connectable.connect() as connection:
        # 配置迁移上下文
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # 使用批处理模式，以处理 sqlite 约束变化
        )

        # 开启事务
        with context.begin_transaction():
            # 运行迁移
            context.run_migrations()



if context.is_offline_mode():
    # 如果处于离线模式
    run_migrations_offline()
    # 执行离线迁移
else:
    # 否则
    run_migrations_online()
    # 执行在线迁移

