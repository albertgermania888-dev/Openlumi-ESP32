import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import media_player
from esphome.const import CONF_ID

DEPENDENCIES = ['media_player']

gateway_player_ns = cg.esphome_ns.namespace("gateway_player")
GatewayMediaPlayer = gateway_player_ns.class_("GatewayMediaPlayer", media_player.MediaPlayer, cg.Component)

# Умная функция для получения правильной схемы в любой версии ESPHome
def get_base_schema():
    if hasattr(media_player, 'media_player_schema'):
        try:
            # Для новых версий (ESPHome 2024.x - 2026.x)
            return media_player.media_player_schema(GatewayMediaPlayer)
        except TypeError:
            return media_player.media_player_schema()
            
    if hasattr(media_player, 'MEDIA_PLAYER_SCHEMA'):
        # Для старых версий
        return media_player.MEDIA_PLAYER_SCHEMA
        
    # Резервный вариант: базовая схема любой сущности Home Assistant
    return getattr(cv, 'ENTITY_BASE_SCHEMA', cv.Schema({}))

CONFIG_SCHEMA = get_base_schema().extend({
    cv.GenerateID(): cv.declare_id(GatewayMediaPlayer),
}).extend(cv.COMPONENT_SCHEMA)

async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await media_player.register_media_player(var, config)
