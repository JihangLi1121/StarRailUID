from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from .login import page_login

sv_sr_login = SV("sr登录")


@sv_sr_login.on_command(("登录", "登陆", "登入", "login"))
async def get_sr_login_msg(bot: Bot, ev: Event):
    return await page_login(bot, ev)
