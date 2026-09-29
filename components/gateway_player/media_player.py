import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import media_player
from esphome.const import CONF_ID

DEPENDENCIES = ['media_player']

gateway_player_ns = cg.esphome_ns.namespace("gateway_player")
GatewayMediaPlayer = gateway_player_ns.class_("GatewayMediaPlayer", media_player.MediaPlayer, cg.Component)

# Используем полноценную базовую схему медиаплеера
CONFIG_SCHEMA = media_player.MEDIA_PLAYER_SCHEMA.extend({
    cv.GenerateID(): cv.declare_id(GatewayMediaPlayer),
}).extend(cv.COMPONENT_SCHEMA)

async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await media_player.register_media_player(var, config)
