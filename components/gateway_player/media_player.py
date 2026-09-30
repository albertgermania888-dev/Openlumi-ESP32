import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import media_player
from esphome.const import CONF_ID

DEPENDENCIES = ['media_player']

gateway_player_ns = cg.esphome_ns.namespace("gateway_player")
GatewayMediaPlayer = gateway_player_ns.class_("GatewayMediaPlayer", media_player.MediaPlayer, cg.Component)

# 1. Формируем безопасную базовую схему
schema = cv.Schema({
    cv.GenerateID(): cv.declare_id(GatewayMediaPlayer),
}).extend(cv.COMPONENT_SCHEMA)

# 2. Динамически подтягиваем схему медиаплеера (работает на всех версиях ESPHome)
if hasattr(media_player, 'media_player_schema'):
    try:
        schema = schema.extend(media_player.media_player_schema(GatewayMediaPlayer))
    except Exception:
        try:
            schema = schema.extend(media_player.media_player_schema())
        except Exception:
            pass
elif hasattr(media_player, 'MEDIA_PLAYER_SCHEMA'):
    schema = schema.extend(media_player.MEDIA_PLAYER_SCHEMA)

# 3. Принудительно задаем ключи, без которых падает ESPHome >= 2026.x
def ensure_keys(config):
    if 'disabled_by_default' not in config:
        config['disabled_by_default'] = False
    if 'internal' not in config:
        config['internal'] = False
    return config

CONFIG_SCHEMA = cv.All(schema, ensure_keys)

async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await media_player.register_media_player(var, config)
