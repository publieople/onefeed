"""OneFeed 宿主应用（003-host-app）。

插件运行时在 plugin_runtime/，这个包只做"把插件数据变成人看得见的界面"：
store（SQLite）→ api（HTTP）→ web（前端）。入口是 python -m onefeed。
"""

__all__ = ["__version__"]
__version__ = "0.3.0.dev0"
