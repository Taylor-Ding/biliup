import asyncio

import httpx

# Set up for non-mainland China networks
# 设置非中国大陆网络的配置
HTTP_TIMEOUT = 15
# HTTP超时时间设置为15秒

# 创建一个httpx的异步客户端，支持HTTP/2协议，自动处理重定向，超时时间为HTTP_TIMEOUT
client = httpx.AsyncClient(http2=True, follow_redirects=True, timeout=HTTP_TIMEOUT)

# 获取当前运行的事件循环
loop = asyncio.get_running_loop()

