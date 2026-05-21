"""xpage mock 包。

启动方式：
    pip install '.[xpage_mock]'
    UPSTREAM_MP_BASE=https://models-proxy.stepfun-inc.com \
    UPSTREAM_MP_KEY=ak-xxx \
    XPAGE_LISTEN_KEYS=test-key-1 \
    uvicorn xpage_mock.server:app --port 8800
"""

__version__ = "0.0.1"
