import json
import re
from pathlib import Path
from typing import List, Tuple, cast

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.message_models import Button
from gsuid_core.models import Event
from gsuid_core.sv import SV
from gsuid_core.utils.database.api import get_uid
from gsuid_core.utils.database.models import GsBind
from gsuid_core.utils.image.convert import convert_img
from PIL import Image
from starrail_damage_cal.map import SR_MAP_PATH

from ..starrailuid_config.sr_config import get_panel_source
from ..utils.error_reply import UID_HINT
from ..utils.resource.RESOURCE_PATH import TEMP_PATH
from .get_char_img import draw_char_info_img
from .panel_data import PANEL_SOURCE_CONFIG_KEY, PANEL_SOURCE_HINT
from .to_card import api_to_card

# ---- path data for weapon selector ----
_PATH_DATA_FILE = Path(__file__).parent.parent / "utils" / "excel" / "path_data.json"
_PATH_DATA = {}
if _PATH_DATA_FILE.exists():
    with open(_PATH_DATA_FILE, encoding="utf-8") as f:
        _PATH_DATA = json.load(f)


def _resolve_char_path(char_name: str) -> str:
    """Resolve a character name to its path (e.g. 'Warrior')."""
    char_paths = _PATH_DATA.get("char_paths", {})
    for cid, cname in SR_MAP_PATH.avatarId2Name.items():
        if cname.lower() == char_name.lower():
            return char_paths.get(cid, "")
    return ""


def _get_weapon_buttons(char_name: str) -> List[Button]:
    """Get compatible Light Cone buttons for a character's path."""
    path_to_lcs = _PATH_DATA.get("path_to_lcs", {})
    path = _resolve_char_path(char_name)
    if not path:
        return []

    lcs = path_to_lcs.get(path, [])
    buttons = []
    # Discord limit: 5 action rows, connector uses 2 buttons/row = 10 max
    for lc_info in lcs:
        lcid = lc_info["id"]
        lc_name = SR_MAP_PATH.EquipmentID2Name.get(lcid, "")
        if not lc_name:
            continue
        star = "⭐" if lc_info.get("rarity", 4) >= 5 else ""
        buttons.append(
            Button(f"{star}{lc_name}", f"sr查询{char_name}换{lc_name}")
        )
        if len(buttons) >= 10:
            break
    return buttons


# ---- standard two-button layout for character cards ----
def _card_buttons(char_name: str) -> List[Button]:
    return [
        Button("🔄更换武器", f"sr更换武器{char_name}"),
        Button("⏫提高命座", f"sr查询六魂{char_name}"),
    ]


sv_char_info_config = SV("sr面板设置", pm=2)
sv_get_char_info = SV("sr面板查询", priority=10)
sv_get_sr_original_pic = SV("sr查看面板原图", priority=5)
sv_weapon_picker = SV("sr武器选择", priority=10)

_SOURCE_MAP = {
    "米游社": "auto",
    "mys": "auto",
    "mihomo": "mihomo",
    "自动": "auto",
    "auto": "auto",
}


# ---- Step 1: character query → card + [更换武器] [提高命座] ----
@sv_get_char_info.on_prefix("查询")
async def send_char_info(bot: Bot, ev: Event):
    name = ev.text.strip()
    if not name:
        return

    im = await _get_char_info(bot, ev, ev.text)
    if isinstance(im, str):
        await bot.send(im)
    elif isinstance(im, Tuple):
        if isinstance(im[0], Image.Image):
            img = await convert_img(cast(Image.Image, im[0]))
        else:
            img = str(im[0])
        await bot.send_option(img, _card_buttons(name))
        if im[1]:
            with Path.open(TEMP_PATH / f"{ev.msg_id}.jpg", "wb") as f:
                f.write(cast(bytes, im[1]))
    elif isinstance(im, Image.Image):
        await bot.send(await convert_img(im))
    elif isinstance(im, bytes):
        await bot.send_option(im, _card_buttons(name))
    elif im is None:
        return
    else:
        await bot.send("发生未知错误")


# ---- Step 2: click 更换武器 → show LC picker buttons ----
@sv_weapon_picker.on_command(("更换武器",))
async def send_weapon_picker(bot: Bot, ev: Event):
    char_name = ev.text.strip()
    if not char_name:
        return await bot.send("请指定角色名")

    # Extract character name (strip Chinese/English)
    char_name = " ".join(re.findall(r"[\u4e00-\u9fa5a-zA-Z&•]+", char_name))
    if not char_name:
        return await bot.send("请指定角色名")

    buttons = _get_weapon_buttons(char_name)
    if not buttons:
        return await bot.send(f"未找到 {char_name} 的可用光锥数据")

    await bot.send_option(
        f"请选择要为【{char_name}】更换的光锥:",
        buttons,
    )


async def _get_char_info(bot: Bot, ev: Event, text: str):
    msg = text
    if not msg:
        return None
    logger.info("开始执行[查询角色面板]")
    if "换" in msg or "拿" in msg or "带" in msg:
        uid = await get_uid(bot, ev, GsBind, "sr", False)
    else:
        uid = await get_uid(bot, ev, GsBind, "sr")
        msg = " ".join(re.findall(r"[\u4e00-\u9fa5a-zA-Z&•·]+", text))
    if uid is None:
        return await bot.send(UID_HINT)
    logger.info(f"[查询角色面板]uid: {uid}")

    return await draw_char_info_img(msg, uid)


@sv_get_char_info.on_command(("强制刷新", "刷新面板"))
async def send_card_info(bot: Bot, ev: Event):
    uid = await get_uid(bot, ev, GsBind, "sr")
    if uid is None:
        return await bot.send(UID_HINT)
    logger.info(f"[sr强制刷新]uid: {uid}")
    im = await api_to_card(uid)
    logger.info(f"UID{uid}获取角色数据成功!")
    if isinstance(im, Tuple):
        buttons = [
            Button(
                f"✅查询{SR_MAP_PATH.avatarId2Name[str(avatarid)]}",
                f"sr查询{SR_MAP_PATH.avatarId2Name[str(avatarid)]}",
            )
            for avatarid in im[1]
        ]
        return await bot.send_option(im[0], buttons)
    return await bot.send(im)


@sv_char_info_config.on_command(("数据源",))
async def set_panel_source(bot: Bot, ev: Event):
    """Explain the global panel source config."""
    source = ev.text.strip()
    current_source = get_panel_source()
    if source and source not in _SOURCE_MAP:
        return await bot.send(PANEL_SOURCE_HINT)
    if source:
        return await bot.send(
            f"面板数据源已改为全局配置, 请在插件配置项 {PANEL_SOURCE_CONFIG_KEY} 中设置为: "
            f"{_SOURCE_MAP[source]}\n当前值: {current_source}"
        )
    return await bot.send(f"当前全局面板数据源: {current_source}\n{PANEL_SOURCE_HINT}")
