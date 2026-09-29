import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import media_player
from esphome.const import CONF_ID, CONF_NAME

DEPENDENCIES = ['media_player']

gateway_player_ns = cg.esphome_ns.namespace("gateway_player")
GatewayMediaPlayer = gateway_player_ns.class_("GatewayMediaPlayer", media_player.MediaPlayer, cg.Component)

CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(): cv.declare_id(GatewayMediaPlayer),
    cv.Required(CONF_NAME): cv.string,
}).extend(cv.COMPONENT_SCHEMA)

async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    # Напрямую задаем имя и регистрируем сущность в Home Assistant
    cg.add(var.set_name(config[CONF_NAME]))
    await media_player.register_media_player(var, config)
